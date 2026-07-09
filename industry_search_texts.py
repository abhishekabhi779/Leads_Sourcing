"""
Search phrases for each industry label.

The semantic search embeds every phrase separately (one vector per phrase, a
few hundred rows total) and an industry's score for a query is its single
best-matching phrase. Bare labels rarely contain the words people search —
the phrase lists are what let a query like "plumbers" or "mortgage brokers"
land on the right industry. Short per-phrase vectors matter: one
pooled vector over a long keyword list dilutes each keyword until single-word
queries ("plumbers", "wineries") barely register.

Keys must exactly match the industry names produced by NAICS_MAP /
NAICS_SECTOR_MAP in load_data.py. Any industry missing from this dict falls
back to embedding just its label (see iter_search_phrases).
"""

INDUSTRY_KEYWORDS = {
    # ── Food service & hospitality (72) ──────────────────────────────────────
    "Bars & Drinking Places":
        "bars, pubs, taverns, nightclubs, cocktail lounges, sports bars, breweries with taprooms, wine bars",
    "Fast Food & Limited-Service Restaurants":
        "fast food restaurants, takeout, quick service, coffee shops, cafes, food trucks, pizza delivery, sandwich shops, ice cream shops, juice bars",
    "Full-Service Restaurants":
        "sit-down restaurants, diners, bistros, steakhouses, family restaurants, fine dining, italian mexican chinese and other ethnic restaurants, seafood restaurants",
    "Restaurants & Food Services":
        "restaurants, catering companies, food service contractors, cafeterias, mobile food vendors",
    "Hotels & Accommodation":
        "hotels, motels, inns, bed and breakfasts, resorts, lodging, RV parks, campgrounds, vacation rentals",
    "Food Service & Hospitality":
        "restaurants, hotels, catering, hospitality businesses, food and beverage service",

    # ── Entertainment & recreation (71) ──────────────────────────────────────
    "Amusement & Recreation":
        "gyms, fitness centers, yoga studios, golf courses, bowling alleys, amusement parks, arcades, marinas, sports clubs, dance studios, martial arts schools",
    "Museums & Cultural Institutions":
        "museums, art galleries, historical sites, zoos, botanical gardens, aquariums",
    "Performing Arts":
        "theaters, performing arts companies, musicians, bands, dance companies, event promoters, artists, entertainers, sports teams",
    "Entertainment & Recreation":
        "entertainment venues, recreation businesses, leisure activities, event spaces",

    # ── Healthcare & social services (62) ────────────────────────────────────
    "Nursing & Residential Care":
        "nursing homes, assisted living facilities, retirement homes, residential care, group homes, hospice care",
    "Hospitals":
        "hospitals, medical centers, surgical hospitals, psychiatric hospitals, emergency care",
    "Outpatient & Medical Clinics":
        "doctors offices, dentists, dental clinics, chiropractors, physical therapy, optometrists, mental health counselors, urgent care clinics, medical labs, home health care, physicians, orthodontists, dermatologists",
    "Healthcare & Social Services":
        "healthcare providers, daycare centers, child care, social services, family services, medical practices, vocational rehabilitation",

    # ── Education (61) ───────────────────────────────────────────────────────
    "Schools & Education":
        "schools, private schools, tutoring centers, driving schools, trade schools, colleges, training centers, language schools, test prep, montessori schools",
    "Education":
        "educational services, schools, training, instruction, academies",

    # ── Administrative & support (56) ────────────────────────────────────────
    "Waste Management":
        "waste collection, garbage hauling, recycling, junk removal, septic services, hazardous waste disposal, remediation",
    "Business Support Services":
        "staffing agencies, employment agencies, janitorial services, cleaning companies, landscaping, lawn care, security guards, pest control, call centers, travel agencies, document shredding, office administrative services",
    "Administrative & Support Services":
        "administrative services, facilities support, business support, outsourcing services",

    # ── Professional services (54) ───────────────────────────────────────────
    "Professional & Technical Services":
        "law firms, lawyers, attorneys, accounting firms, CPAs, bookkeepers, tax preparers, architects, engineering firms, IT consulting, software development companies, computer services, marketing agencies, advertising agencies, graphic design, management consultants, veterinarians, veterinary clinics, surveyors, interior designers, photographers, scientific research",
    "Professional Services":
        "professional service firms, consultants, technical experts, business advisors",

    # ── Real estate & rental (53) ────────────────────────────────────────────
    "Equipment Rental":
        "equipment rental, tool rental, car rental, truck rental, party equipment rental, leasing companies",
    "Real Estate":
        "real estate agents, realtors, property management, real estate brokers, apartment leasing, commercial real estate, real estate appraisers, landlords",
    "Real Estate & Rental":
        "real estate businesses, rental companies, leasing services, property services",

    # ── Finance & insurance (52) ─────────────────────────────────────────────
    "Insurance":
        "insurance agencies, insurance brokers, insurance carriers, life insurance, auto insurance, health insurance agents, claims adjusters, title insurance",
    "Banks, Credit Unions & Lenders":
        "banks, commercial banks, community banks, savings banks, retail banking, credit unions, mortgage lenders, mortgage brokers, loan companies, consumer lending, financing companies, credit card issuers",
    # NAICS 521 — real banks are under 522; these 12-odd rows are misreported
    # codes, so keep the phrases too narrow for "banks" queries to land here.
    "Central Banking & Monetary Authorities":
        "monetary authorities, central banking",
    "Finance & Insurance":
        "financial services, investment firms, wealth management, financial advisors, stock brokers, securities brokerages, hedge funds, payroll services, banks, insurance companies, portfolio management, financial planners",

    # ── Tech, media & telecom (51) ───────────────────────────────────────────
    "Web & Internet Publishing":
        "websites, internet publishers, online content, web portals, search portals, digital media companies",
    "Data Processing & Hosting":
        "data centers, web hosting, cloud services, data processing, IT infrastructure, SaaS companies",
    "Telecommunications":
        "telecom companies, internet service providers, wireless carriers, phone companies, satellite communications, cable providers",
    "Broadcasting":
        "radio stations, television stations, TV networks, broadcasters, streaming media",
    "Film & Music":
        "film production, video production companies, recording studios, music producers, movie theaters, post-production",
    "Publishing":
        "book publishers, newspaper publishers, magazine publishers, software publishers, video game publishers, directories",
    "Technology, Media & Telecom":
        "technology companies, software companies, tech startups, media companies, information services, digital businesses",

    # ── Transportation & warehousing (48–49) ─────────────────────────────────
    "Warehousing & Storage":
        "warehouses, storage facilities, self storage, cold storage, distribution centers, fulfillment centers",
    "Couriers & Delivery":
        "couriers, delivery services, package delivery, messenger services, last mile delivery",
    "Trucking":
        "trucking companies, freight hauling, long haul trucking, moving companies, movers, dump truck services, owner operators, logistics carriers",
    "Water Transportation":
        "shipping companies, marine transport, ferries, barge operators, boat charters",
    "Rail Transportation":
        "railroads, rail freight, train transportation",
    "Air Transportation":
        "airlines, air charter, air cargo, helicopter services, private aviation",
    "Transportation":
        "taxi services, limousine services, shuttle services, school buses, ride share drivers, transit, ambulance services, towing, freight brokers, packing and crating",
    "Transportation & Warehousing":
        "transportation companies, logistics, freight, shipping, distribution",

    # ── Retail (44–45) ───────────────────────────────────────────────────────
    "Gas Stations":
        "gas stations, fuel stations, convenience stores with gas, truck stops",
    "Health & Personal Care Retail":
        "health stores, vitamin shops, supplement stores, cosmetics stores, beauty supply stores, optical goods stores",
    "General Merchandise & Department Stores":
        "department stores, discount stores, dollar stores, general stores, warehouse clubs, supercenters",
    "Online & Nonstore Retail":
        "online stores, ecommerce, internet retailers, mail order, vending machine operators, direct sales",
    "Miscellaneous Retail":
        "florists, gift shops, pet stores, used merchandise stores, thrift stores, art dealers, tobacco shops, office supply stores",
    "Sporting Goods, Books & Hobby Stores":
        "sporting goods stores, bike shops, gun shops, bookstores, hobby shops, toy stores, music instrument stores, craft stores",
    "Clothing & Accessories":
        "clothing stores, boutiques, shoe stores, jewelry stores, apparel retailers, accessories shops",
    "Pharmacies & Drug Stores":
        "pharmacies, drug stores, prescription drugs retail",
    "Grocery & Food Stores":
        "grocery stores, supermarkets, convenience stores, liquor stores, butcher shops, bakeries retail, specialty food stores, health food stores, markets",
    "Home Improvement & Hardware":
        "hardware stores, home improvement stores, lumber yards, paint stores, garden centers, nurseries, building supply",
    "Electronics & Appliance Stores":
        "electronics stores, appliance stores, computer stores, cell phone stores",
    "Furniture & Home Furnishings":
        "furniture stores, mattress stores, home decor stores, flooring stores, window treatment stores",
    "Auto Dealers & Parts":
        "car dealerships, auto dealers, used car lots, auto parts stores, motorcycle dealers, boat dealers, RV dealers, tire stores",
    "Retail Trade":
        "retail stores, shops, retailers, merchants, storefronts",

    # ── Wholesale (42) ───────────────────────────────────────────────────────
    "Non-Durable Goods Wholesale":
        "wholesale distributors of food, beverages, groceries, apparel, paper, chemicals, petroleum, flowers",
    "Durable Goods Wholesale":
        "wholesale distributors of machinery, equipment, vehicles, furniture, lumber, metals, electronics, hardware",
    "Wholesale Trade":
        "wholesalers, distributors, import export companies, suppliers, B2B distribution",

    # ── Manufacturing (31–33) ────────────────────────────────────────────────
    "Miscellaneous Manufacturing":
        "manufacturers of medical devices, jewelry, signs, sporting goods, toys, office supplies",
    "Furniture Manufacturing":
        "furniture makers, cabinet makers, custom cabinetry, millwork, kitchen cabinets, wood furniture manufacturing",
    "Transportation Equipment Manufacturing":
        "auto parts manufacturers, vehicle manufacturing, boat builders, aerospace parts, trailer manufacturers",
    "Electronics Manufacturing":
        "electronics manufacturers, circuit boards, semiconductors, instruments, computer hardware manufacturing",
    "Machinery Manufacturing":
        "machinery manufacturers, industrial equipment, machine builders, HVAC equipment manufacturing, engines",
    "Metal Products Manufacturing":
        "metal fabrication shops, machine shops, welding shops, sheet metal work, CNC machining, structural steel fabricators, metal stamping, tool and die shops",
    "Primary Metal Manufacturing":
        "steel mills, foundries, metal casting, aluminum production, smelting",
    "Plastics Manufacturing":
        "plastics manufacturers, injection molding, rubber products, plastic fabrication",
    "Chemical Manufacturing":
        "chemical manufacturers, pharmaceutical manufacturing, paint manufacturing, soap and cleaning products, cosmetics manufacturing",
    "Printing & Publishing":
        "print shops, commercial printing, screen printing, sign printing, book printing",
    "Wood Products Manufacturing":
        "sawmills, wood product manufacturers, pallet makers, engineered wood, custom woodworking",
    "Apparel Manufacturing":
        "clothing manufacturers, garment factories, textile products, embroidery, cut and sew apparel",
    "Food & Beverage Manufacturing":
        "food processing plants, commercial bakeries, wineries, breweries, distilleries, beverage bottlers, meat processing, dairy processing, snack food makers",
    "Manufacturing":
        "manufacturers, factories, production plants, industrial manufacturing, fabricators",

    # ── Construction (23) ────────────────────────────────────────────────────
    "Specialty Trade Contractors":
        "plumbers, electricians, HVAC contractors, roofers, roofing companies, painters, drywall contractors, flooring installers, concrete contractors, masonry, framing carpenters, excavation, demolition, siding, glass and glazing, insulation contractors, tile installers",
    "Civil & Heavy Construction":
        "road construction, highway contractors, bridge builders, utility line construction, land development, heavy civil engineering construction",
    "Building Construction":
        "general contractors, home builders, residential construction, commercial construction, remodeling contractors, custom home builders",
    "Construction":
        "construction companies, contractors, builders, construction trades",

    # ── Utilities (22) ───────────────────────────────────────────────────────
    "Utilities":
        "electric utilities, water utilities, natural gas distribution, power companies, solar power generation",

    # ── Mining & energy (21) ─────────────────────────────────────────────────
    "Oil & Gas Support Services":
        "oilfield services, drilling support, well servicing, fracking services",
    "Mining":
        "mining companies, quarries, sand and gravel, stone mining, coal mining",
    "Oil & Gas Extraction":
        "oil and gas producers, petroleum extraction, natural gas wells, energy exploration",
    "Mining & Energy":
        "mining, oil and gas, energy companies, natural resources extraction",

    # ── Agriculture (11) ─────────────────────────────────────────────────────
    "Agricultural Support Services":
        "farm support services, crop harvesting, soil preparation, agricultural consulting, cotton ginning, farm labor contractors",
    "Fishing & Hunting":
        "commercial fishing, fisheries, hunting and trapping, seafood harvesting",
    "Forestry & Logging":
        "logging companies, timber, forestry, tree harvesting",
    "Animal Production & Ranching":
        "ranches, cattle ranching, livestock farms, poultry farms, dairy farms, hog farms, horse breeding, apiaries, aquaculture",
    "Crop Farming":
        "farms, crop farming, vegetable farms, fruit orchards, vineyards, grain farming, greenhouses, nurseries, hay farming, organic farms",
    "Agriculture & Farming":
        "farms, agriculture, farming operations, agricultural producers",

    # ── Personal & repair services (81) ──────────────────────────────────────
    "Personal Care Services":
        "hair salons, barber shops, barbershops, nail salons, beauty salons, day spas, tanning salons, tattoo parlors, massage therapists, dry cleaners, laundromats, funeral homes, pet grooming, weight loss centers, personal trainers",
    "Repair & Maintenance":
        "auto repair shops, auto body shops, car mechanics, collision repair, oil change shops, transmission repair, appliance repair, electronics repair, computer repair, small engine repair, furniture upholstery, welding repair, equipment maintenance",
    "Personal & Repair Services":
        "personal services, repair services, churches, religious organizations, nonprofits, civic associations, professional associations, parking lots, photofinishing",

    # ── Government (92) ──────────────────────────────────────────────────────
    "Government & Public Administration":
        "government agencies, municipalities, public administration, tribal governments",

    # ── Fallback ─────────────────────────────────────────────────────────────
    "Other / Unknown":
        "unclassified businesses, miscellaneous companies, unknown industry",
}


def iter_search_phrases(sector, industry):
    """Yield every phrase to embed for one (sector, industry) pair.

    Always includes the industry label itself (so queries phrased as category
    names match), then each comma-separated keyword phrase on its own. No
    boilerplate templates — shared prefixes like "sector: ... | industry: ..."
    inflate cosine similarity between unrelated categories and drown the signal.
    """
    seen = set()
    for phrase in [industry] + INDUSTRY_KEYWORDS.get(industry, "").split(","):
        phrase = phrase.strip()
        if phrase and phrase.lower() not in seen:
            seen.add(phrase.lower())
            yield phrase
