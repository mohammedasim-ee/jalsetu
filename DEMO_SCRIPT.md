# 5-minute demo script

**Before class:**
- Open the live site once so the server is warm.
- Log in on `/admin` in a second tab, using the admin account set in the Vercel environment variables.
- Have the GitHub repository open in a third tab.

## 0:00 Opening (20 s)

> "JalSetu is a data-driven water-security platform for Bengaluru. It answers four questions: what is happening to the city's water, what could happen next, why the risk is changing, and what to do. It is a working prototype. The figures are official and published data, each shown with its source and date. It is not a live government feed."

## 0:20 Overview: the risk score and why (60 s)

1. Point at the gauge: **67 / 100, HIGH**.
   > "This isn't a hard-coded number. The server combines six indicators with documented weights."
2. Read the top two bars:
   - "Groundwater: 186.7% extraction, the official CGWB 2024 figure. Anything over 100 is full risk: +25."
   - "Rainfall: 48% below normal this monsoon: +20."
3. Open **Full explanation and data freshness**.
   > "Every input shows its source, date and status. Reservoirs are from 5 September; groundwater from 2024. The system shows how old each input is."
4. Scroll to **Early warnings**: the ALERT for borewell-dependent areas.
   > "This rule fires because low rain AND over-pumping happen together. It comes with suggested actions."

## 1:20 Rain + ML: real data, real evaluation (80 s)

1. Point at the 117-year chart.
   > "Official IMD data 1901–2017. Red bars are deficient monsoons, including the 2016 drought. The trend is actually increasing, which is statistically significant, p = 0.0006."
2. **Load a past year: 2002** → **Run the model**.
   > "At the end of July, the Random Forest gives a high deficient-monsoon risk score, and here is why: the June–July shortfall contributes most. The contributions add up exactly to the score. 2002 really was deficient, about −33%, though that year was in the training data."
3. Scroll to **How accurate are the models?**
   > "Honest result: on 87 test seasons the model catches 4 of 6 deficient monsoons, and it does not beat a simple rule on F1. It even scores the 2016 drought just under its cut-off. So the warning engine uses the rule, and the model is shown as a ranking score. And for next-month rainfall, no model beat the long-term average, so JalSetu uses the average and says so."

## 2:40 Map (30 s)

1. Point at the ward boundaries.
   > "243 real BBMP ward boundaries from KGIS, lakes from Wikipedia, and reports placed in their ward."
2. Tap a ward.
   > "No ward-level rainfall or groundwater data is public, so I deliberately don't colour wards by risk."

## 3:10 Report → admin review (60 s)

1. **Report** tab: Groundwater issue, Whitefield, a description and a photo → **Submit**.
   > "It's saved in PostgreSQL, the photo is resized on the server, the ward is found automatically, and the status is Submitted."
2. Switch to the **admin** tab: **Under review** → **Verified**.
   > "The status change is enforced by a state machine and written to the audit log."
3. Back on **Overview**: the community bar now shows 1 verified report.
   > "Only verified reports affect the score, so spam can't move it."

## 4:10 Failing case + exchange (30 s)

1. In admin, try Verified → Submitted: there's no button for it. Mention that the API returns 409 for disallowed moves.
2. **Quality**: type nitrate 60 → **Unsafe**.
   > "The standard allows no relaxation for nitrate, and every limit is IS 10500:2012."

## 4:40 Close (20 s)

> "Everything I showed is tested: 119 automated Python tests, including a browser test that runs this exact journey, plus 9 frontend tests. The risk methodology, model report, data sources and security review are all in the repository. Limitations are documented too: regional rainfall data ends in 2015, some figures come from news reports of official data, and there is no ward-level risk."

## If something fails

| Problem | What to do |
| --- | --- |
| No internet | Run it locally: `uvicorn app.main:app` |
| Map tiles don't load | The ward outlines still render; say so |
| Admin login fails | The `ADMIN_EMAIL` / `ADMIN_PASSWORD` environment variables aren't set on Vercel; show the review workflow in the `test_report_review_workflow_and_audit` test instead |
