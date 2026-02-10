# Agent Run Summary

## Instruction
Extract key financial and covenant terms from this agreement and answer the questions.

## Extracted Signals
- **facility_amount**: $250 million
- **interest_terms**: Margin, SOFR, interest rate
- **covenants**: Interest Coverage Ratio, Leverage Ratio
- **events_of_default**: Events of Default, default
- **maturity**: Maturity Date

## Q&A
### Q: What is the facility amount?
Question: What is the facility amount?
Answer basis (evidence):
- [doc-0:p1:b7] (p1) Borrower may request up to $250 million revolving commitments.
Consistency: not_supported (0.0)

### Q: What are the financial covenants?
Question: What are the financial covenants?
Answer basis (evidence):
- [doc-0:p1:b9] (p1) Section 6.02 Financial Covenants
Consistency: supported (1.0)

### Q: What is the maturity date?
Question: What is the maturity date?
Answer basis (evidence):
- [doc-0:p1:b4] (p1) "Maturity Date" means March 31, 2031.
Consistency: supported (1.0)
