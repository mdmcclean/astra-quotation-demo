"""Offline quotation pilot. Integer cents, stable retry IDs, PDF and matching CSV.

No network, customer sending, payment collection, or tax-rate determination.
"""
import argparse
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import textwrap


def label(value, maximum=100):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("Missing or oversized quotation text")
    if any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ValueError("This pilot supports printable English ASCII text only")
    return value.strip()


def normalize(data):
    required = {"seller", "customer", "date", "currency", "tax_basis_points", "items", "sample"}
    if not isinstance(data, dict) or set(data) != required or data["currency"] != "USD" or type(data["sample"]) is not bool:
        raise ValueError("Expected the documented USD quotation schema")
    from datetime import date
    date.fromisoformat(data["date"])
    tax = data["tax_basis_points"]
    if type(tax) is not int or not 0 <= tax <= 10000:
        raise ValueError("Tax must be a supplied rate in basis points, between 0 and 10000")
    if not isinstance(data["items"], list) or not 1 <= len(data["items"]) <= 200:
        raise ValueError("Supply 1 to 200 line items")
    items = []
    for item in data["items"]:
        if not isinstance(item, dict) or set(item) != {"description", "quantity", "unit_price_cents"}:
            raise ValueError("Invalid line item")
        if not isinstance(item["quantity"], str) or len(item["quantity"]) > 12:
            raise ValueError("Quantity must be a decimal string")
        try:
            quantity = Decimal(item["quantity"])
            if not quantity.is_finite() or not 0 < quantity <= 100000 or quantity != quantity.quantize(Decimal("0.01")):
                raise ValueError("Quantity must be positive with at most two decimal places")
        except InvalidOperation as exc:
            raise ValueError("Invalid quantity") from exc
        cents = item["unit_price_cents"]
        if type(cents) is not int or not 0 <= cents <= 100000000:
            raise ValueError("Unit prices must be nonnegative integer cents")
        amount = int((quantity * cents).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        items.append({"description": label(item["description"], 180), "quantity": format(quantity, "f"), "unit_price_cents": cents, "amount_cents": amount})
    subtotal = sum(i["amount_cents"] for i in items)
    if subtotal > 10000000000:
        raise ValueError("Quotation exceeds the pilot's supported total")
    tax_cents = int((Decimal(subtotal) * tax / 10000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return {"seller": label(data["seller"]), "customer": label(data["customer"]), "date": data["date"], "currency": "USD", "sample": data["sample"], "tax_basis_points": tax, "items": items, "subtotal_cents": subtotal, "tax_cents": tax_cents, "total_cents": subtotal + tax_cents}


def money(cents):
    return f"${cents // 100:,}.{cents % 100:02d}"


def pdf(document):
    """Small, dependency-free PDF writer with repeated page headers and totals."""
    def escaped(value):
        return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    pages, commands = [], []
    page_number = 0
    y = 0
    def text(x, yy, value, size=10, bold=False, color="0.12 0.17 0.24"):
        font = "F2" if bold else "F1"
        commands.append(f"{color} rg BT /{font} {size} Tf 1 0 0 1 {x} {yy} Tm ({escaped(value)}) Tj ET")
    def new_page():
        nonlocal commands, y, page_number
        if commands:
            pages.append("\n".join(commands).encode("ascii"))
        commands = []
        page_number += 1
        commands.append("0.06 0.12 0.20 rg 0 690 612 102 re f")
        text(42, 754, "QUOTATION", 25, True, "1 1 1")
        text(42, 727, document["number"] + "  |  " + document["date"], 11, False, "0.75 0.87 0.94")
        line_y = 668
        for line in textwrap.wrap(document["seller"], 40):
            text(42, line_y, line, 13, True)
            line_y -= 16
        line_y -= 6
        for line in textwrap.wrap("Prepared for: " + document["customer"], 52):
            text(42, line_y, line)
            line_y -= 14
        header_y = min(600, line_y - 22)
        text(42, header_y, "DESCRIPTION", 9, True)
        text(365, header_y, "QTY", 9, True)
        text(417, header_y, "UNIT USD", 9, True)
        text(505, header_y, "AMOUNT", 9, True)
        commands.append(f"0.75 0.80 0.86 RG 42 {header_y - 10} m 570 {header_y - 10} l S")
        text(42, 35, "SYNTHETIC SAMPLE - NOT A BILL" if document["sample"] else "DRAFT - STAFF APPROVAL REQUIRED", 9, True)
        text(520, 35, f"Page {page_number}", 9)
        y = header_y - 30
    new_page()
    for item in document["items"]:
        lines = textwrap.wrap(item["description"], 32)
        height = max(1, len(lines)) * 14 + 14
        if y - height < 100:
            new_page()
        for i, line in enumerate(lines):
            text(42, y - i * 14, line)
        text(365, y, item["quantity"], 9)
        text(417, y, money(item["unit_price_cents"]), 9)
        text(505, y, money(item["amount_cents"]), 9)
        y -= height
    if y < 195:
        new_page()
    y -= 20
    for key, title in (("subtotal_cents", "Subtotal"), ("tax_cents", f"Tax ({document['tax_basis_points'] / 100:g}%)"), ("total_cents", "TOTAL USD")):
        text(355, y, title, 11, key == "total_cents")
        text(475, y, money(document[key]), 11, key == "total_cents")
        y -= 24
    pages.append("\n".join(commands).encode("ascii"))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"]
    kids = []
    for stream in pages:
        page_id = len(objects) + 1
        kids.append(f"{page_id} 0 R")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {page_id + 1} 0 R >>".encode())
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{n} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(output)


def csv_bytes(document):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["quote_number", "row_type", "description", "quantity", "unit_price_cents", "amount_cents", "currency"])
    for item in document["items"]:
        description = item["description"]
        if description.startswith(("=", "+", "-", "@")):
            description = "'" + description
        writer.writerow([document["number"], "item", description, item["quantity"], item["unit_price_cents"], item["amount_cents"], "USD"])
    for key in ("subtotal_cents", "tax_cents", "total_cents"):
        writer.writerow([document["number"], key, "", "", "", document[key], "USD"])
    return out.getvalue().encode("utf-8")


def generate(data, request_id, directory):
    document = normalize(data)
    request_id = label(request_id, 100)
    digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(directory / "quotes.sqlite3", timeout=10) as db:
        db.execute("CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE, digest TEXT, manifest TEXT)")
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT digest,manifest FROM quotes WHERE request_id=?", (request_id,)).fetchone()
        if previous:
            if previous[0] != digest:
                raise ValueError("Retry ID already belongs to different inputs")
            manifest = json.loads(previous[1])
            for name, expected in manifest["sha256"].items():
                path = directory / manifest["number"] / name
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError("Stored quotation artifact is missing or has changed")
            return manifest
        seq = db.execute("INSERT INTO quotes(request_id,digest) VALUES (?,?)", (request_id, digest)).lastrowid
        document["number"] = f"AST-{seq:06d}"
        payloads = {"quotation.pdf": pdf(document), "quotation.csv": csv_bytes(document), "quotation.json": (json.dumps(document, indent=2) + "\n").encode()}
        manifest = {"number": document["number"], "request_id": request_id, "total_cents": document["total_cents"], "sha256": {name: hashlib.sha256(body).hexdigest() for name, body in payloads.items()}}
        staged = Path(tempfile.mkdtemp(prefix=".quote-", dir=directory))
        try:
            for name, body in payloads.items():
                with (staged / name).open("wb") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
            destination = directory / document["number"]
            if destination.exists():
                raise ValueError("Unregistered output exists; inspect before retrying")
            os.replace(staged, destination)
            db.execute("UPDATE quotes SET manifest=? WHERE id=?", (json.dumps(manifest), seq))
        finally:
            if staged.exists():
                shutil.rmtree(staged)
        return manifest


def build_sample(directory):
    """Fixed synthetic acceptance case used by the backend. Never a financial record."""
    data = {"seller": "Astra document automation - demonstration", "customer": "Example Field Services (fictional)", "date": "2026-11-12", "currency": "USD", "tax_basis_points": 825, "sample": True, "items": [{"description": "Example inspection visit", "quantity": "2", "unit_price_cents": 12500}, {"description": "Example preparation hours", "quantity": "1.50", "unit_price_cents": 6000}]}
    first = generate(data, "synthetic-existing-customer-v1", directory)
    if first["total_cents"] != 36805 or generate(data, "synthetic-existing-customer-v1", directory) != first:
        raise ValueError("Sample totals or retry acceptance failed")
    second = generate({**data, "customer": "Example New Customer (fictional)"}, "synthetic-new-customer-v1", directory)
    if first["number"] == second["number"]:
        raise ValueError("Sample unique numbering failed")
    return {"status": "sample_ready", "synthetic": True, "acceptance": ["Expected total 36805 cents", "Identical retry returns identical artifacts", "New customer receives a distinct quote number"], "quotes": [first, second]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(json.loads(args.input.read_text()), args.request_id, args.output), indent=2))
