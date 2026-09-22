"""Labeled triage set. Synthetic on purpose — the CFPB public complaint database stopped exposing consumer
narratives in 2025, so there is no current public corpus of real borrower letters (the older narratives are
mirrored elsewhere; cfpb.py builds the real set from them). Labels are ground truth by construction:
each letter was written to be one thing, with the traps a mailroom actually sees (no loan number, several
asks in one letter, lawyer letters, payoff inside an RFI, a dispute phrased politely, OCR-style noise).

Fields: case_type; error_category (NOE only); rfi_category (RFI only); loan (whether a loan identifier is
recoverable from the text); exceptions the model should at least flag.
"""

LETTERS: list[dict] = [
    # ---- plain NOE by category -----------------------------------------------------------------------------
    dict(id="noe-b5-fee", case_type="NOE", error_category="b5", loan=True, text="""Rebecca Lindqvist
Loan 5510-220-9931

I was charged a $95 "property inspection fee" on my statement. Nobody inspected anything — I live in the house
and have never missed a payment. Please remove it and tell me what it was for."""),
    dict(id="noe-b2-misapplied", case_type="NOE", error_category="b2", loan=True, text="""Re: account ending 4471 (Thomas & Ana Reyes)

We sent an extra $2,000 with our March payment and wrote "apply to principal" on the check. Your statement shows
it went to "unapplied funds" and our principal balance did not change. Please apply it to principal as instructed."""),
    dict(id="noe-b3-late-credit", case_type="NOE", error_category="b3", loan=True, text="""Loan #88120034
Karim Haddad

My payment was received by you on the 1st (I have the certified mail receipt) but you posted it on the 6th and
charged a late fee. Payments must be credited as of the day you receive them. Please correct the posting date."""),
    dict(id="noe-b4-escrow", case_type="NOE", error_category="b4", loan=True, text="""Account 3302-118-0057 — Priyanka Rao

The county sent me a delinquency notice because my property taxes were not paid from escrow in November. You collect
escrow every month. Why were the taxes not paid, and who is covering the penalty?"""),
    dict(id="noe-b6-payoff-wrong", case_type="NOE", error_category="b6", loan=True, text="""To: Servicing Department
From: Marcus Bell, loan 7001-554-2210

The payoff statement you issued on the 14th shows a balance $3,400 higher than my last statement's principal plus
one month of interest. I think the payoff figure is wrong. Please recalculate it before my closing on the 30th."""),
    dict(id="noe-b7-lossmit-info", case_type="NOE", error_category="b7", loan=True, text="""Loan 2210-909-1188 / Gloria Nwosu

Your representative told me on the phone that I was "not eligible for any assistance" and that I had to be 90 days
behind to apply. Your own website says otherwise. I was given wrong information about my options and I want that
corrected in writing."""),
    dict(id="noe-b8-transfer", case_type="NOE", error_category="b8", loan=True, text="""Re: loan 4488-000-1123, borrower Hiro Tanaka

My loan was transferred to you from my previous servicer in April. You are showing me as two payments behind. I have
every confirmation from the old servicer: I was current on the transfer date. Their records were not carried over
correctly."""),
    dict(id="noe-b10-sale", case_type="NOE", error_category="b10", loan=True, text="""URGENT — loan 9090-321-4477, Dolores Mendez

I submitted a complete loan modification application on August 2 and you confirmed it was complete. You have now
scheduled a foreclosure sale for October 3. You cannot proceed to a sale while my complete application is under
review. Cancel the sale."""),
    dict(id="noe-b11-other", case_type="NOE", error_category="b11", loan=True, text="""Loan 1200-778-3344
Samuel Okonkwo

You have my mailing address wrong — statements are going to my old apartment and I only found out because a
neighbor forwarded one. I updated my address twice by phone. Please fix your records and confirm in writing."""),
    # ---- RFI -----------------------------------------------------------------------------------------------
    dict(id="rfi-owner", case_type="RFI", rfi_category="OWNER_IDENTITY", loan=True, text="""Account 6633-410-0021 — Wen Li

Please tell me the name, address and telephone number of the current owner or assignee of my mortgage loan. I
need this for a legal matter."""),
    dict(id="rfi-other-history", case_type="RFI", rfi_category="OTHER", loan=True, text="""Loan 5566-778-9900
Janet Brooks

I am requesting a complete payment history for my loan from origination to today, showing how each payment was
applied between principal, interest, escrow and fees."""),
    dict(id="rfi-other-escrow-analysis", case_type="RFI", rfi_category="OTHER", loan=True, text="""Account 2020-303-4040, Ahmed Saleh

My monthly payment went up $180. Please send me the escrow analysis that explains the change and the amounts
you expect to pay for taxes and insurance next year."""),
    dict(id="rfi-owner-polite", case_type="RFI", rfi_category="OWNER_IDENTITY", loan=True, text="""Hello,

This is Fatima Zahra, loan number 7788-990-0112. I hope you're well. Could you let me know who actually holds
my note these days? I've had three different names on my statements and I'd like to know who I'm really paying.

Thanks so much."""),
    # ---- payoff -------------------------------------------------------------------------------------------
    dict(id="payoff-plain", case_type="PAYOFF_REQUEST", loan=True, text="""Loan 3131-414-5151 — Luis and Carmen Ortiz

We are selling the house. Please send a payoff statement good through November 15, 2026 to us and to our
closing attorney, whose authorization is attached."""),
    dict(id="payoff-via-attorney", case_type="PAYOFF_REQUEST", loan=True, text="""LAW OFFICES OF R. GREENE
Re: Your borrower Emily Cho, loan no. 8181-616-2323

We represent Ms. Cho in the sale of the above property. Enclosed is her signed authorization. Kindly furnish a
written payoff statement as of October 20, 2026, including per-diem interest."""),
    # ---- loss mitigation ----------------------------------------------------------------------------------
    dict(id="lossmit-hardship", case_type="LOSS_MIT", loan=True, text="""Loan 4545-656-7878
Derek Washington

My hours were cut in half in July and I am going to fall behind next month. I want to apply for whatever
assistance is available — a modification, forbearance, anything. What do you need from me?"""),
    dict(id="lossmit-forbearance-end", case_type="LOSS_MIT", loan=True, text="""Account 9191-020-3030 — Nadia Petrova

My forbearance ends in December. I cannot pay the missed amounts in a lump sum. I would like to be considered
for a deferral or a repayment plan."""),
    # ---- not covered --------------------------------------------------------------------------------------
    dict(id="not-covered-coupon", case_type="NOT_COVERED", loan=True, text="""Payment enclosed. Loan 2323-454-5656. $1,842.17. Please apply to October. — B. Kowalski"""),
    dict(id="not-covered-address-change", case_type="NOT_COVERED", loan=True, text="""Loan 6767-898-0101, Sandra Mills

Effective November 1 my mailing address will be 42 Harbor Lane, Apt 3, Portland ME 04101. Please update your
records. Thank you."""),
    dict(id="not-covered-compliment", case_type="NOT_COVERED", loan=False, text="""Just wanted to say your phone agent Marcus was wonderful last week and sorted out my question in five minutes.
More companies should be like this. — Ellen"""),
    # ---- traps ---------------------------------------------------------------------------------------------
    # First label was loan=False. The model returned the property address — and §1024.35(a) asks for "information
    # that enables the servicer to identify the account", which an address is. The label was wrong, not the model.
    dict(id="trap-no-loan-number", case_type="NOE", error_category="b5", loan=True, text="""To whom it may concern,

I am writing about the late charges on my mortgage. I have paid on time for eleven years and suddenly there are
two late fees on my account. I would like them removed. My name is Harold Finch and my property is at 1 Elm
Street. I don't have my loan number with me."""),
    dict(id="trap-two-asks", case_type="NOE", error_category="b4", loan=True, text="""Loan 5050-606-7070 — Maria Santos

Two things. First, my homeowner's insurance was not paid from escrow and the policy lapsed — that is your error
and I want it fixed and any lapse fees reversed. Second, while you are at it, please send me the payoff amount
as of the end of the year; I may refinance."""),
    dict(id="trap-overbroad", case_type="NOE", error_category="b11", loan=False, exceptions=["OVERBROAD"], text="""This whole loan has been a nightmare since day one and I want everything looked at and fixed. — J. Alvarez"""),
    dict(id="trap-duplicative-hint", case_type="NOE", error_category="b3", loan=True, exceptions=["DUPLICATIVE"], text="""Loan 1414-252-3636 — Owen Blackwood

This is the THIRD time I am writing about the same thing. As I said in my letters of May 3 and June 20, my
payments are being posted late and I am being charged late fees. You already answered once and said there was
no error. There is. Please look again."""),
    dict(id="trap-ocr-noise", case_type="RFI", rfi_category="OTHER", loan=True, text="""Loan  #  9 8 7 6 - 5 4 3 - 2 1 0 0
Fr0m: Angela Ruiz

P1ease send me c0pies of the last twelve monthly statements. I d0 not have online access and the ones you
mailed were lost in a move."""),
    dict(id="trap-payoff-inside-rfi", case_type="RFI", rfi_category="OTHER", loan=True, text="""Account 2626-373-4848, Kevin Doyle

I'd like a breakdown of how my last payment was applied, a copy of my note, and the current payoff amount."""),
    dict(id="trap-foreclosure-date", case_type="NOE", error_category="b9", loan=True, text="""Loan 7373-848-9595 — Beatrice Lam

You filed for foreclosure on September 9, 2026. I was only 95 days delinquent on that date — I have your own
statements showing it. You are not allowed to make the first filing before 120 days. This filing is improper."""),
    dict(id="trap-question-not-error", case_type="RFI", rfi_category="OTHER", loan=True, text="""Loan 8484-959-0606
Iris Nakamura

Why did my payment amount change in September? I did not get a letter. Please explain the new amount."""),
    # ---- hard ------------------------------------------------------------------------------------------
    # Added after the first 28 scored 28/28 on Gemini: a set the model aces measures the set, not the model.
    # These are letters where the label needs a reason (`note`), where the schema itself is the limit, or where
    # a second answer is defensible (`alt_case_type` — scored as a hit, reported separately).
    dict(id="hard-both-noe-and-rfi", case_type="NOE", error_category="b2", loan=True, alt_case_type="RFI",
         note="One letter, two covered requests. §1024.35 and §1024.36 each start their own clocks; the schema holds one case_type, so the operator must open the RFI by hand. Schema limit, not model error.",
         text="""Loan 6161-727-8383 — Patrick O'Neill

My September payment of $2,210 shows as "unapplied" on the October statement and I was charged a late fee on top.
Please apply it to September as it should have been. Separately, please send me a full transaction history for
2026 so I can see where every dollar went."""),
    dict(id="hard-payoff-no-keyword", case_type="PAYOFF_REQUEST", loan=True,
         note="No 'payoff' anywhere. Reg Z §1026.36(c)(3) covers any request for the amount to satisfy the obligation.",
         text="""Account 2727-838-9494
Denise Carter

I came into some money and I want to be done with this mortgage. What is the exact figure to close out the loan
entirely if I wire it on December 1? Include whatever interest is due to that day."""),
    dict(id="hard-ocr-loan-digits", case_type="NOE", error_category="b5", loan=True,
         note="OCR read 5→S and 0→O in the loan number. The quote must be the letter's text as-is; a model that 'fixes' the digits is inventing, which the verbatim check catches.",
         text="""Loan 5S1O-22O-99E1
Rebecca Lindqvist

There is a $45 "payment processing fee" on my statement for paying by check. I have always paid by check and
was never charged before. Please remove it."""),
    dict(id="hard-rate-complaint", case_type="NOT_COVERED", loan=True,
         note="Says 'wrong' and 'error' but asserts no servicing error: the rate is a contract term (comment 35(b)-2 excludes origination). Keyword triage fails here.",
         text="""Loan 3838-949-0505 — Victor Alonso

My interest rate is 7.1% and my neighbor just got 5.9%. This is wrong and I think there was an error when I
signed. I want a lower rate."""),
    dict(id="hard-denial-appeal", case_type="LOSS_MIT", loan=True, alt_case_type="NOE",
         note="An appeal of a loss-mitigation denial has its own route (§1024.41(h), 14 days). Calling it an NOE (b)(11) is defensible; what matters is that the operator sees the appeal deadline, which the LOSS_MIT route surfaces and the NOE route does not.",
         text="""Loan 4949-050-6161 — Monica Reyes

You denied my loan modification on September 12 saying my income was insufficient. That is an error — you used
my old pay stubs, not the ones I sent in August. I want this decision reviewed and reversed."""),
    dict(id="hard-informal-owner", case_type="RFI", rfi_category="OWNER_IDENTITY", loan=False,
         note="Text-message register, no loan number, no name. Still a §1024.36 owner/assignee request: 10-day clock.",
         text="""hey did u guys sell my loan?? got a letter from some company i never heard of saying to pay them now. who
actually owns it and who do i pay"""),
    dict(id="hard-third-time-escrow", case_type="RFI", rfi_category="OTHER", loan=True, exceptions=["DUPLICATIVE"],
         note="Duplicative is an exception the operator confirms against the file; the model should flag it, not decide it.",
         text="""Account 5252-636-7474 — George Adebayo

For the third time: please send me the escrow analysis you did in March. I wrote on April 4 and again on
June 1. I have received nothing but the same form letter."""),
    dict(id="hard-b6-with-sale-date", case_type="NOE", error_category="b6", loan=True,
         note="A foreclosure sale date appears, but the asserted error is the payoff figure: (b)(6), 7 days. The sale date must be recorded (it caps b9/b10 clocks) without pulling the category to b9/b10.",
         text="""Loan 6363-747-8585 — Henry Voss

My house is set for foreclosure sale on November 20. I have a buyer and can pay the loan off before then, but
the payoff statement you sent lists $12,000 in "corporate advances" that were never explained and are not on
any statement. The payoff figure is wrong. I need a correct one this week."""),
    dict(id="hard-untimely-old-loan", case_type="NOE", error_category="b11", loan=True, exceptions=["UNTIMELY"],
         note="Loan paid off in 2024; §1024.35(g)(1)(iii) lets the servicer decline notices received more than a year after transfer or discharge — but only after checking the file.",
         text="""Former loan 7474-858-9696, paid off March 2024 — Lillian Marsh

I just discovered you reported my account as 30 days late in January 2024 to the credit bureaus. It was never
late. I want it corrected."""),
    dict(id="hard-everything-in-file", case_type="RFI", rfi_category="OTHER", loan=True, exceptions=["OVERBROAD|BURDENSOME"],
         note="'Every document' is the textbook §1024.36(f)(1)(iv) request. The rule has one exception, 'overbroad or unduly burdensome'; the schema split it into two flags, so either counts.",
         text="""Loan 8585-969-0707 / Ahmed Siddiqui

Send me every document, note, email, recording and record you have about my loan from the day it was opened."""),
    dict(id="hard-holiday-question", case_type="NOT_COVERED", loan=False,
         note="A question mark is not a request for information about the loan. Keyword triage says RFI.",
         text="""Are your offices open on Columbus Day? I want to drop off a payment in person that morning. Thanks — Ruth"""),
    dict(id="hard-lawyer-address-only", case_type="NOE", error_category="b1", loan=True,
         note="Attorney letter with property address only. The address is 'information that enables the servicer to identify' the loan (§1024.35(a)); loan=True.",
         text="""HALPERN & WU, ATTORNEYS AT LAW
Re: Our client Daniel Kim, property at 88 Ridge Road, Unit 4B, Jersey City NJ 07302

Our client tendered his full October payment by cashier's check on October 1. Your office returned it on October
9 with a note that "partial payments are not accepted." The payment was not partial; it was the full contractual
amount. Demand is made that you accept and credit it as of October 1."""),
    dict(id="hard-transfer-who-to-pay", case_type="RFI", rfi_category="OTHER", loan=True,
         note="Post-transfer confusion. Not an owner-identity request — the borrower asks where to pay and whether the number changed, which is 'other' information (30 days).",
         text="""Loan 9696-070-1818 — Chloe Bennett

I got a letter saying my servicing moved to you on October 1. Is my loan number still the same? Where do I send
November's payment, and will my autopay carry over?"""),
    dict(id="hard-question-that-is-an-error", case_type="RFI", rfi_category="OTHER", loan=True, alt_case_type="NOE",
         note="Phrased as a question but hints at an escrow error. CFPB: a servicer may treat an ambiguous letter as an RFI if it cannot identify an asserted error; NOE (b)(4)/(b)(11) is defensible. Either way the operator reads it.",
         text="""Account 0707-181-2929 — Samir Patel

Can you explain why my escrow payment went up $400 a month when my property taxes went down this year? That
doesn't seem right to me."""),
]
