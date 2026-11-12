# Quotation automation pilot

Turn structured quotation inputs into a numbered PDF and matching CSV, ready for staff review. This is an AI-assisted software demonstration using fictional data. It is not a customer case study, invoice, or claim of paid work.

## Proposed pilot

**$75 USD fixed test price:** adapt one English/USD quotation layout to one agreed input schema, supply the Python source, a sample input, PDF/CSV outputs, and run instructions. Includes one revision against the agreed template. Proposed turnaround: two business days after the template, input example, acceptance criteria and payment terms are agreed. Price and demand have not been validated with buyers.

The first scope is an offline generator. CRM, messaging, payment collection, deployment, ongoing support and additional templates are separate work. Customers supply and approve their own tax rate and business wording. Printable ASCII text is supported; international character sets are outside this first pilot.

## Try the demonstration

Requires Python 3.12 or later. No packages, network connection, cloud account, API key or paid API calls are needed.

```sh
python3 quotation.py example.json --request-id demo-001 --output ./output
```

Open `output/AST-000001/quotation.pdf`. The same folder contains `quotation.csv` and `quotation.json`. Keep `output/quotes.sqlite3` with the output files: it holds numbering and retry identity. Run the same command again to receive the same number and artifact hashes. For a genuinely new quotation, use a new request ID. Reusing an ID with different input is rejected.

Input fields: seller, customer, ISO date, currency (`USD`), tax rate in basis points (825 = 8.25%), sample flag, and 1–200 items. Each item has a description, quantity as a decimal string with at most two decimal places, and a nonnegative integer unit price in cents. All calculations use decimal quantities and integer cents; line amounts and total tax round half up. CSV monetary columns are cents, not dollars. Formula-like descriptions are escaped in CSV.

## Acceptance criteria

1. The supplied example produces subtotal **$340.00**, supplied-rate tax **$28.05**, and total **$368.05**, identically in PDF, JSON and CSV.
2. Same request ID and same inputs return the same quotation number and identical artifacts. Changed inputs under that ID fail clearly.
3. A new request ID receives a distinct number, including for a new customer.
4. Long descriptions wrap and multi-page quotations retain headers, page numbers and a final total.
5. Invalid amounts and quantities fail; retries detect missing or modified output files.
6. The generator runs locally without sending customer data or creating a financial transaction.

The included sample files are synthetic. A paid pilot would additionally be checked against the buyer's approved template and examples. The proposal is subject to an agreed scope and payment route; no order or contract is accepted by publishing this demonstration.

## Evidence and limits

Automated checks cover totals, rounding, concurrent retry identity, different customers, long descriptions, invalid values and changed-file detection. Independent PDF parsing and rendering were used to inspect generated output. This is a narrow first release; it has no editor, authenticated hosting, e-signatures, automated sending or accounting-system connection.

Development used AI assistance. The runtime is deterministic Python. No customer references, professional certifications or employment history are claimed.
