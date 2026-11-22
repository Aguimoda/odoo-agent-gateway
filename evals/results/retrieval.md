# Retrieval evaluation

Model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 24 questions (18 answerable, 6 unanswerable), threshold 0.42, run 2026-11-22.

| hit@1 | hit@3 | MRR | quiet on unanswerable | mean noise |
|---|---|---|---|---|
| 0.83 | 0.94 | 0.88 | 1.00 | 0.00 |

## Threshold sweep

| threshold | hit@3 | MRR | quiet | noise |
|---|---|---|---|---|
| 0.20 | 0.94 | 0.88 | 0.00 | 3.67 |
| 0.21 | 0.94 | 0.88 | 0.00 | 3.50 |
| 0.22 | 0.94 | 0.88 | 0.00 | 3.33 |
| 0.23 | 0.94 | 0.88 | 0.00 | 3.00 |
| 0.24 | 0.94 | 0.88 | 0.00 | 3.00 |
| 0.25 | 0.94 | 0.88 | 0.00 | 2.67 |
| 0.26 | 0.94 | 0.88 | 0.00 | 2.17 |
| 0.27 | 0.94 | 0.88 | 0.17 | 1.83 |
| 0.28 | 0.94 | 0.88 | 0.17 | 1.83 |
| 0.29 | 0.94 | 0.88 | 0.17 | 1.33 |
| 0.30 | 0.94 | 0.88 | 0.17 | 1.33 |
| 0.31 | 0.94 | 0.88 | 0.50 | 0.83 |
| 0.32 | 0.94 | 0.88 | 0.50 | 0.67 |
| 0.33 | 0.94 | 0.88 | 0.67 | 0.33 |
| 0.34 | 0.94 | 0.88 | 0.67 | 0.33 |
| 0.35 | 0.94 | 0.88 | 0.67 | 0.33 |
| 0.36 | 0.94 | 0.88 | 0.67 | 0.33 |
| 0.37 | 0.94 | 0.88 | 0.83 | 0.17 |
| 0.38 | 0.94 | 0.88 | 0.83 | 0.17 |
| 0.39 | 0.94 | 0.88 | 0.83 | 0.17 |
| 0.40 | 0.94 | 0.88 | 0.83 | 0.17 |
| 0.41 | 0.94 | 0.88 | 1.00 | 0.00 |
| 0.42 | 0.94 | 0.88 | 1.00 | 0.00 |
| 0.43 | 0.94 | 0.88 | 1.00 | 0.00 |
| 0.44 | 0.89 | 0.86 | 1.00 | 0.00 |
| 0.45 | 0.89 | 0.86 | 1.00 | 0.00 |
| 0.46 | 0.89 | 0.86 | 1.00 | 0.00 |
| 0.47 | 0.83 | 0.81 | 1.00 | 0.00 |
| 0.48 | 0.83 | 0.81 | 1.00 | 0.00 |
| 0.49 | 0.83 | 0.81 | 1.00 | 0.00 |
| 0.50 | 0.83 | 0.81 | 1.00 | 0.00 |
| 0.51 | 0.83 | 0.81 | 1.00 | 0.00 |
| 0.52 | 0.83 | 0.81 | 1.00 | 0.00 |
| 0.53 | 0.78 | 0.78 | 1.00 | 0.00 |
| 0.54 | 0.72 | 0.72 | 1.00 | 0.00 |
| 0.55 | 0.72 | 0.72 | 1.00 | 0.00 |
| 0.56 | 0.72 | 0.72 | 1.00 | 0.00 |
| 0.57 | 0.72 | 0.72 | 1.00 | 0.00 |
| 0.58 | 0.72 | 0.72 | 1.00 | 0.00 |
| 0.59 | 0.72 | 0.72 | 1.00 | 0.00 |
| 0.60 | 0.67 | 0.67 | 1.00 | 0.00 |

## Per question

| id | expected | rank | top score |
|---|---|---|---|
| returns-who-es | returns.md | 1 | 0.688 |
| returns-window-en | returns.md | 1 | 0.753 |
| returns-register-es | returns.md | 1 | 0.462 |
| returns-refund-en | returns.md | 1 | 0.810 |
| returns-custom-es | returns.md | - | 0.501 |
| shipping-canary-es | shipping.md | 1 | 0.721 |
| shipping-mainland-en | shipping.md | 1 | 0.770 |
| shipping-free-en | shipping.md | 1 | 0.535 |
| shipping-floor-es | shipping.md | 1 | 0.624 |
| shipping-damaged-es | shipping.md | 3 | 0.501 |
| discounts-max-es | discounts.md | 1 | 0.596 |
| discounts-approval-en | discounts.md | 1 | 0.616 |
| discounts-promise-en | discounts.md | 1 | 0.637 |
| payments-terms-es | payments.md | 1 | 0.656 |
| payments-overdue-en | payments.md | 1 | 0.813 |
| payments-cash-es | payments.md | 1 | 0.616 |
| payments-first-order-en | payments.md | 2 | 0.558 |
| payments-reminder-es | payments.md | 1 | 0.624 |
| none-wifi-es | (none) | - | 0.326 |
| none-holidays-en | (none) | - | 0.304 |
| none-ceo-en | (none) | - | 0.364 |
| none-parking-es | (none) | - | 0.408 |
| none-cars-en | (none) | - | 0.267 |
| none-pension-es | (none) | - | 0.301 |
