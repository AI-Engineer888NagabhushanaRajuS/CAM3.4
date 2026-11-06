# Teach 2 - The BOM: reading the parts list

Everything in this domain orbits one artifact: the Bill of Materials. Learn to read it and 80% of the files stop being mysterious.

## What a BOM literally is

A BOM is a recipe. A recipe says "for 1 cake: 200g flour, 2 eggs, 100g sugar." A BOM says "for 1 control unit: 1 PCB, 68 connector contacts, 1 FPGA, 6 fasteners, 1 ESD bag, 0.0056 pallets."

Yes - a fraction of a pallet. REAL row from the sample workbook (tab 'CBOM Proto', row 32):

| Part | Description | Qty per unit | Unit |
|---|---|---|---|
| 87093547V00-PALLET | Pallet | 0.005555... | NO (count) |

0.00555... = 1/180. One pallet carries 180 units, so each unit "consumes" 1/180th of a pallet. BOMs carry fractional quantities for shared packing materials, wire sold per meter, and similar. When you see a tiny decimal quantity, that is why.

## The 10 columns of the Scrub BOM (REAL header, tab '1.0 Scrub BOM')

`FG | Level | Assembly | CPN | Description | MFR | MPN | Commodity | Quantity | UOM`

- **FG** - Finished Good: which final product this part ends up in. One project can build 11 different finished goods.
- **Level** - how deep in the product tree the part sits. Level 0 = the finished product itself. Level 1 = things bolted directly onto it. Level 2 = parts inside those parts. A BOM is a tree, and Level is the depth.
- **Assembly** - which sub-assembly the part belongs to.
- **CPN** - Centum Part Number: Centum's own ID for the part. THE key column of the whole system. Everything - quotes, prices, stock, reports - hangs off the CPN.
- **MPN** - Manufacturer Part Number: the maker's own catalog ID (e.g. MICROCHIP's `A3P1000-FGG256I`). Suppliers quote against MPNs; Centum tracks CPNs. Mapping one to the other is constant, error-prone work.
- **MFR** - the manufacturer (as opposed to the supplier, who resells).
- **Commodity** - the part family: ACTIVE (chips), PASSIVE (resistors/caps), PCB, ELECTROMECHANICAL, FASTENERS, PACKING, PCBA... Commodities drive which buyer handles the part and what scrap rate applies.
- **UOM** - Unit of Measure: NUM/NO/EA = count, M = meters.

REAL first rows of the Scrub BOM (project CE-005405):

| FG | Level | CPN | Description | Commodity | Qty |
|---|---|---|---|---|---|
| E16233DA | 0 | E16233DA | Carte FAV FCU SA | PCBA | 1 |
| E16233DA | 1 | E16233DA-ESD | ESD 460mm x 101mm | Packing | 1 |
| E16233DA | 1 | E16233DA-Packing | Packing 470mm x 111mm x 25mm | Packing | 1 |

Read row 1 like the French it partly is: the finished good E16233DA is itself a PCBA ("carte" = board). Rows 2-3: each unit ships in one anti-static bag and one packing box. Level 0 sells; level 1 is what it directly consumes.

## From client BOM to Scrub BOM

The customer does not send this clean table. They send their own format (see BOM-Centum (1).xlsx for a real one) with their own column names, merged cells, odd spellings. "Scrubbing" is the human+tool pass that converts it: standardize columns to the 10 above, resolve MPN/CPN mismatches, fill commodity, fix quantities. The instructions doc in the project (CAM - Instructions for Creating a Scrub BOM) is exactly this procedure. The scrub template (CAM - Costed BOM Input Template.xlsx) defines the required columns, and the colmap skill doc records the header-name mappings across client formats (exact-match headers, typo-intolerant - Teach 6 covers what happens when they are wrong).

## Variant levels: Proto, VL-1 ... VL-4

One quote usually prices the SAME products at different build volumes - prototype quantities vs. volume batches - because suppliers give price breaks at volume. This project prices 5 volume scenarios, one tab set each: Proto, VL-1, VL-2, VL-3, VL-4. The Batch Qty settings tab holds the per-assembly volumes, e.g. REAL: assembly 87093547V00 = 850 (V1), 630 (V2), 420 (V3)...; E16233DA = 885 / 700 / 450.

## Check yourself

1. In tab '1.0 Scrub BOM', find a level-2 part. What is its assembly?
2. Why is CPN the key and not MPN? (Hint: one CPN can map to several approved MPNs; who owns the quote pipeline?)
3. A wire row shows UOM=M, Qty=3.2335. What does that mean physically?
4. E16233DA-ESD has the same prefix as the FG. What naming convention does that suggest for child packing parts?

Next: Teach 3 - follow one part through the whole RFQ pipeline.
