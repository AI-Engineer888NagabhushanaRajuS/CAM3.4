# Teach 1 - What is an RFQ? The kid version

## The birthday party story

Imagine you are throwing a birthday party for 200 people. You need 200 plates, 200 cups, 50 balloons, 3 cakes, and a magician.

You do not just walk into one shop and pay whatever they ask. Instead you write your list on paper and send copies to three different party shops. Each shop writes back: "plates: 2 rupees each, cups: 1.50, balloons we do not sell, cake: 800 each, delivery in 4 days."

Now you compare. Shop A is cheap for plates but has no balloons. Shop B sells everything but costs more. Shop C is cheapest but delivers in 3 weeks - too late. You mix and match, and now you know exactly what the party will cost before you spend a single rupee.

That piece of paper you sent to the shops is an RFQ: **Request for Quotation**. You are requesting that each shop quote you a price.

## Now make it electronics

Centum Electronics builds circuit boards and box-build products for customers like Thales, Siemens, Hitachi Energy. A customer's product - say a control unit for a train - contains maybe 1,000 different electronic parts: chips, resistors, connectors, cables, the printed circuit board itself, screws, labels, packing boxes.

When the customer asks "what will it cost to build this?", Centum cannot guess. It does the birthday-party thing at industrial scale:

1. The customer sends the parts list. That list is the **BOM - Bill of Materials** (next lesson).
2. Centum cleans the list up (fixes typos, fills gaps, standardizes part numbers). The cleaned list is the **Scrub BOM**.
3. Centum sends the list to many **suppliers** (the shops): Avnet, Mouser, Souriau, small local vendors. Each supplier quotes prices for the parts they sell.
4. Centum merges all the quotes, picks winners per part, converts everything into one currency, multiplies by quantities, and adds it all up.
5. The result is a **Costed BOM (CBOM)**: the same list, but now every part has a price and the whole product has a cost. That cost, plus margin, becomes the price Centum quotes back to the customer.

That is the whole business of these files. Everything else - 43 Excel tabs, 422,645 formulas, 5 software modules - exists to do those 5 steps faster and with fewer mistakes.

## The words you just learned, in plain language

- **RFQ (Request for Quotation)**: asking sellers "what will you charge me for this list?"
- **Quote**: a seller's answer - prices, minimum order sizes, delivery times.
- **BOM (Bill of Materials)**: the complete parts list for one product.
- **Supplier / Vendor**: a company that sells parts.
- **OEM / Customer**: the company that designed the product and wants it built (Thales, Siemens...).
- **EMS (Electronics Manufacturing Services)**: what Centum is - a company that builds electronics designed by others.
- **Costed BOM (CBOM)**: the BOM with prices filled in and totalled.

## Why it is hard (the reason CAM exists)

The party list had 5 items. A real Centum BOM has ~1,000-5,000 line items across ~11 product variants. For each part: several suppliers quote, in different currencies (EUR, INR, USD), with conditions (minimum order quantity, price breaks at volume, lead times). And a mistake is not "we bought too many balloons" - the project's own incident report records a run where one output tab overstated the Letter of Award value by +245% versus the correct quote (see Teach 6). Getting it right by hand takes the team about 2 days per quote; the CAM automation target is about 2 hours.

## Check yourself

1. Explain to a rubber duck why Centum does not just buy every part from one supplier.
2. In the birthday story, what plays the role of the Scrub BOM? (Hint: when you rewrote your list neatly so all three shops could read it.)
3. Open Domain 1 and find three glossary terms this lesson used without defining. 

Next: Teach 2 - the BOM itself, the list that everything else is about.
