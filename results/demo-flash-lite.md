# Demo: splitbill on Gemini 3.1 Flash-Lite

4 of 5 issues verified · 80,649 tokens · models: gemini-3.1-flash-lite/gemini-3.1-flash-lite

| Issue | Result | Model calls | Tokens | Time |
|---|---|---|---|---|
| [#1](https://github.com/learn-dumboo24/issue-to-repro-demo/issues/1) Amounts of ₹1 lakh and above use international grouping instead of lakh/crore | verified: fails now, passes with the fix | 7 | 16,658 | 34s |
| [#2](https://github.com/learn-dumboo24/issue-to-repro-demo/issues/2) Splitting ₹100 between 3 people only adds up to ₹99.99 | verified: fails now, passes with the fix | 7 | 14,780 | 15s |
| [#3](https://github.com/learn-dumboo24/issue-to-repro-demo/issues/3) "12.5" is parsed as ₹12.05 instead of ₹12.50 | verified: fails now, passes with the fix | 9 | 24,688 | 24s |
| [#4](https://github.com/learn-dumboo24/issue-to-repro-demo/issues/4) Settle up says "Meera pays Meera ₹0.00" when someone is already even | verified: fails now, passes with the fix | 7 | 13,638 | 13s |
| [#5](https://github.com/learn-dumboo24/issue-to-repro-demo/issues/5) Feature request: split by percentage | no test written | 6 | 10,885 | 44s |
