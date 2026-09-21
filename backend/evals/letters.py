"""Labeled triage set. Synthetic on purpose — the CFPB public complaint database stopped exposing consumer
narratives, so there is no public corpus of real borrower letters. Labels are ground truth by construction:
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
]
