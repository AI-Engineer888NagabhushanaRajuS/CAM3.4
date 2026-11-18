"""Fixed text of the Drills template sheets that have no data behind them in CAM (copied verbatim from the Drills internal workbook
CE-005864 Rev0, including its spelling): the CBOM Checklist rows and the Sales Checklist questions. Generated once; edit by hand if Drills
changes its template. Nothing here is RFQ data."""

# CBOM Checklist: (Category, (Active, Passive, Electromechanical, Electromechnical 2, Mechanical, Consumable, PCB) = who must check the row, Action text)
CBOM_CHECKLIST_COLUMNS = ("Active", "Passive", "Electromechanical", "Electromechnical 2", "Mechanical", "Consumable", "PCB")
CBOM_CHECKLIST_ITEMS = [('Missing Note',
  (True, True, True, False, False, False, True),
  '1).Uncosted part list  with proper Comments.\n'
  '2). Obsolete & EOL part with LTB date.\n'
  '3).Alternate MFR & MPN With proper Comments.\n'
  '4).Customer supported parts list\n'
  '5). NCNR parts.\n'
  '6).Advance Suppliers.\n'
  '7)Long leadtime part list(internal reference)\n'
  '6).Packing dimension(internal reference)'),
 ('Revision History Comment & Validation',
  (False, False, False, False, False, False, True),
  '1).Remarks for All part.\n2).Commodity Comments for Price increased parts'),
 ('MFR & MPN validation as per Scrub BOM', (True, True, True, False, False, True, True), '1). MFR & MPN details sholud be match with Scrub BOM'),
 ('Price & Currency Accurecy',
  (True, True, True, False, False, True, True),
  '1). All part prices and Currency sholud be Capture(if Not needs to be capture in Missing Note).'),
 ('Supplier Name as per System(LN)', (True, True, True, False, False, True, True), '1). Supplier name sholud be Match as per system(LN)'),
 ('SPQ & MOQ', (True, True, True, False, False, True, True), '1). SPQ Should be equal or Lesser than MOQ\n2). MOQ should be multiple of SPQ'),
 ('Lead Time',
  (True, True, True, False, False, True, True),
  '1). Lead time should  be Capture for all Parts\n'
  '2).The lead time for proto should be less than 8 weeks.\n'
  '3).The lead time for Volume should be less than 25 weeks , more than 25  weeks need the remarks and reason for high LT\n'),
 ('Price Control for all parts',
  (True, True, True, False, False, True, True),
  '1). Price Control needs to Capture for all parts( Centum/Contract/Customer)\n2).Thales Project (Centum/TNP/SMS)'),
 ('Quote Validity date for all parts',
  (True, True, True, False, False, True, True),
  '1).Quote Expiry date for all parts.\n2). All volumes supplier Quote expiry date Sholud be Same(expect Online price).\n \n '),
 ('Payment terms for all parts', (True, True, True, False, False, True, True), '1). Payment terms as per Supplier'),
 ('Excess inventory sheet with Comment',
  (True, True, True, False, False, True, False),
  '1).Common parts need to remove excess\n2).Need comment for higher excess parts.\n3).Higher Excess MOQ part, please check the tube package'),
 ('A-Class sheet with Comment', (True, True, True, False, False, False, False), '1).Needs to update comments for high value parts.'),
 ('A-Class parts need to be Checked in our AML dump', (False, True, False, False, False, False, False), None),
 ('EOL & NFRND part Validation', (False, False, True, False, False, False, False), '1). EOL & NRFND part needs to update in Missing Notes'),
 ('Quotes needs to park in Path', (True, True, True, False, False, True, True), '1).All quotation need to save in path'),
 ('Price Negotiation done for A-class parts',
  (False, False, True, False, False, False, True),
  '1). Price Should be Negiotiated for TOP A-class parts'),
 ('Are all Alternate MPN has been explored and CBOM is optimised', (False, False, False, False, False, False, True), None),
 ('Are all A class components negotiated price', (False, False, True, False, False, False, True), None),
 ('Qty Check ', (True, True, True, False, False, True, True), None),
 ('All the above points have been validated across all volumes',
  (True, True, True, False, False, False, True),
  'All volumes need to check the above points')]

# Sales Checklist: the 28 questions in column B
SALES_CHECKLIST_ITEMS = ['Is CBOM revision number generated and mentioned in the CBOM name?',
 'Is CBOM Reviewed by Sourcing Manager? (all CBOM)',
 'Is CBOM Reviewed by SCM Head? ($3M and above & all Must win)',
 'Are all material assumptions clearly mentioned and statement is correct?',
 'Is LTB date mentioned for all EOL/Discontinued parts?',
 'Is MCL Raised date mentioned for all Material Assumptions?',
 'MCLs related to RFQ, need to check and verified by Sourcing Manager',
 'Is Excess cost reviewed by Sourcing manager and optimised?',
 'Are all Alternate MPN has been explored and CBOM is optimised?',
 'Is MFR/Supplier emails for A class components parked in the path?',
 'Are all A class components negotiated price?',
 'Is Lead time for Proto validated? Reason should be given if it is more than 12 weeks',
 'The QTY of each CPN listed in the SCRUB BOM for each FG and Assembly should match with the QTY recorded in the CBOM for the same CPN, Assembly, '
 'and FG. ',
 "Parts with Price as '0' or 'Blank' or '-' in CBOM, should be listed in Missing Notes with Reason for uncosting.",
 'MPN listed in CBOM should match with MPNs listed in SCRUB BOM.',
 'If any different MPN is listed in CBOM, then that MPN should be listed in Missing Notes with reason for changing the MPN.',
 'MPN listed in CBOM should not be Discontinued or EOL or NRFND.\n'
 'If any such MPN is listed in CBOM, then that MPN should be listed in Missing Notes with LTB date.',
 'All Uncosted parts, Non-cancellable & Non-refundable parts should be listed in Missing Notes',
 'Customer support parts with price /FOC should be listed in missing notes ',
 'All Uncosted Parts that are listed should have valid reason.',
 'Revision history: If any change in price (Increase/Decrease), need proper reason ',
 'Price control to be updated for all parts',
 'CBOM validity is checked carefully and is correct (Price Validity)',
 'Payment terms (Advance/Credit)',
 'Commoditiy wise % ',
 'CBOM Currency need to finalise - USD/EURO (Based on buy value)',
 'Proto Quote: Buffer quantity for all passive components (As per package size) to be amortised in Proto quantity',
 'New Supplier list (If Any) is mentioned in missing notes']
