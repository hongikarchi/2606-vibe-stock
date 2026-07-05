"""sic_sectors.py — SEC 4-digit SIC code → finviz 2-level sector taxonomy.

finviz.com/map lays out US stocks as SECTOR (11 top-level GICS-based buckets) →
INDUSTRY. This module maps SEC SIC codes to that (sector, industry) taxonomy so the
treemap can color/group issuers the way finviz does.

Source of truth: finviz.com/map (GICS-based). The placement of a SIC follows what the
real companies under that code actually are on finviz — NOT the literal SIC label —
so e.g. "Hospital & Medical Service Plans" (UnitedHealth) lands in Healthcare, not
Financial/Insurance, and "Drug Stores" (CVS/Walgreens) lands in Healthcare, not
Consumer Defensive.

The 11 sectors (English, canonical): Technology, Healthcare, Financial,
Consumer Cyclical, Consumer Defensive, Communication Services, Industrials, Energy,
Basic Materials, Real Estate, Utilities.

Lookup order in classify():
  1. exact 4-digit SIC code in SIC_MAP,
  2. else a coarse 2-digit-prefix fallback (a reasonable guess by SIC major group),
  3. else ("기타" / "Other" / "Other").
Every SIC code observed in our data is mapped explicitly in SIC_MAP; the fallback only
catches codes we have not yet seen.
"""
from __future__ import annotations

# 4-digit SIC string -> (sector_english, industry_english)
# Industry names follow finviz's taxonomy in the naming style requested by the task
# (e.g. "Banks" not "Banks—Regional", "Utilities-Regulated Electric").
SIC_MAP: dict[str, tuple[str, str]] = {
    # --- Basic Materials ---
    "0100": ("Consumer Defensive", "Farm Products"),      # Agricultural Production-Crops
    "1040": ("Basic Materials", "Gold"),                  # Gold and Silver Ores
    "1400": ("Basic Materials", "Other Industrial Metals & Mining"),  # Nonmetallic Minerals
    "2621": ("Basic Materials", "Paper & Paper Products"),  # Paper Mills
    "2650": ("Consumer Cyclical", "Packaging & Containers"),  # Paperboard Containers
    "2670": ("Basic Materials", "Paper & Paper Products"),  # Converted Paper
    "2810": ("Basic Materials", "Chemicals"),             # Industrial Inorganic Chemicals
    "2821": ("Basic Materials", "Chemicals"),             # Plastic Materials Synth Resins
    "2851": ("Basic Materials", "Specialty Chemicals"),   # Paints Varnishes
    "2860": ("Basic Materials", "Chemicals"),             # Industrial Organic Chemicals
    "2870": ("Basic Materials", "Agricultural Inputs"),   # Agricultural Chemicals
    "3312": ("Basic Materials", "Steel"),                 # Steel Works Blast Furnaces
    "3357": ("Basic Materials", "Other Industrial Metals & Mining"),  # Nonferrous Wire Drawing

    # --- Energy ---
    "1311": ("Energy", "Oil & Gas"),                      # Crude Petroleum & Natural Gas (Exxon)
    "1389": ("Energy", "Oil & Gas Equipment & Services"), # Oil & Gas Field Services
    "2911": ("Energy", "Oil & Gas Refining & Marketing"), # Petroleum Refining
    "4922": ("Energy", "Oil & Gas Midstream"),            # Natural Gas Transmission (pipelines)
    "6792": ("Energy", "Oil & Gas"),                      # Oil Royalty Traders

    # --- Consumer Defensive ---
    "2000": ("Consumer Defensive", "Packaged Foods"),     # Food and Kindred Products
    "2011": ("Consumer Defensive", "Packaged Foods"),     # Meat Packing Plants
    "2033": ("Consumer Defensive", "Packaged Foods"),     # Canned Fruits Veg Preserves
    "2040": ("Consumer Defensive", "Packaged Foods"),     # Grain Mill Products
    "2060": ("Consumer Defensive", "Confectioners"),      # Sugar & Confectionery
    "2070": ("Consumer Defensive", "Packaged Foods"),     # Fats & Oils
    "2080": ("Consumer Defensive", "Beverages"),          # Beverages (Coca-Cola)
    "2082": ("Consumer Defensive", "Beverages - Brewers"),  # Malt Beverages
    "2086": ("Consumer Defensive", "Beverages"),          # Bottled & Canned Soft Drinks
    "2111": ("Consumer Defensive", "Tobacco"),            # Cigarettes
    "2842": ("Consumer Defensive", "Household & Personal Products"),  # Specialty Cleaning
    "2844": ("Consumer Defensive", "Household & Personal Products"),  # Perfumes Cosmetics Toilet
    "5140": ("Consumer Defensive", "Food Distribution"),  # Wholesale-Groceries
    "5331": ("Consumer Defensive", "Discount Stores"),    # Retail-Variety Stores
    "5411": ("Consumer Defensive", "Grocery Stores"),     # Retail-Grocery Stores

    # --- Consumer Cyclical ---
    "1520": ("Consumer Cyclical", "Residential Construction"),  # Bldg Contractors-Residential
    "2300": ("Consumer Cyclical", "Apparel Manufacturing"),  # Apparel
    "2320": ("Consumer Cyclical", "Apparel Manufacturing"),  # Men's & Boys' Furnishings
    "2840": ("Consumer Defensive", "Household & Personal Products"),  # Soap Detergents Cosmetics
    "3021": ("Consumer Cyclical", "Footwear & Accessories"),  # Rubber & Plastics Footwear
    "3100": ("Consumer Cyclical", "Footwear & Accessories"),  # Leather & Leather Products
    "3630": ("Consumer Cyclical", "Furnishings, Fixtures & Appliances"),  # Household Appliances
    "3711": ("Consumer Cyclical", "Auto Manufacturers"),  # Motor Vehicles (Tesla, Ford)
    "5013": ("Consumer Cyclical", "Auto Parts"),          # Wholesale-Motor Vehicle Supplies
    "5200": ("Consumer Cyclical", "Home Improvement Retail"),  # Retail-Bldg Materials Hardware
    "5211": ("Consumer Cyclical", "Home Improvement Retail"),  # Retail-Lumber & Bldg Materials
    "5500": ("Consumer Cyclical", "Auto & Truck Dealerships"),  # Retail-Auto Dealers & Gasoline
    "5651": ("Consumer Cyclical", "Apparel Retail"),      # Retail-Family Clothing Stores
    "5700": ("Consumer Cyclical", "Home Improvement Retail"),  # Retail-Home Furniture Furnishings
    "5731": ("Consumer Cyclical", "Specialty Retail"),    # Retail-Radio TV Consumer Electronics
    "5810": ("Consumer Cyclical", "Restaurants"),         # Retail-Eating & Drinking Places
    "5812": ("Consumer Cyclical", "Restaurants"),         # Retail-Eating Places (McDonald's)
    "5961": ("Consumer Cyclical", "Internet Retail"),     # Retail-Catalog & Mail-Order Houses
    "5990": ("Consumer Cyclical", "Specialty Retail"),    # Retail-Retail Stores NEC
    "7011": ("Consumer Cyclical", "Lodging"),             # Hotels & Motels
    "7841": ("Consumer Cyclical", "Specialty Retail"),    # Services-Video Tape Rental
    "7990": ("Consumer Cyclical", "Leisure"),             # Services-Amusement & Recreation

    # --- Healthcare ---
    "2834": ("Healthcare", "Drug Manufacturers - General"),  # Pharmaceutical Preparations
    "2835": ("Healthcare", "Biotechnology"),              # In Vitro & In Vivo Diagnostic Substances
    "2836": ("Healthcare", "Biotechnology"),              # Biological Products
    "3841": ("Healthcare", "Medical Devices"),            # Surgical & Medical Instruments
    "3842": ("Healthcare", "Medical Instruments & Supplies"),  # Orthopedic Prosthetic Appliances
    "3845": ("Healthcare", "Medical Devices"),            # Electromedical Apparatus
    "3851": ("Healthcare", "Medical Instruments & Supplies"),  # Ophthalmic Goods
    "5047": ("Healthcare", "Medical Distribution"),       # Wholesale-Medical Dental Hospital Equip
    "5122": ("Healthcare", "Medical Distribution"),       # Wholesale-Drugs
    "5912": ("Healthcare", "Pharmaceutical Retailers"),   # Retail-Drug Stores (CVS/Walgreens)
    "6324": ("Healthcare", "Healthcare Plans"),           # Hospital & Medical Service Plans (UNH)
    "8062": ("Healthcare", "Medical Care Facilities"),    # General Medical & Surgical Hospitals
    "8071": ("Healthcare", "Diagnostics & Research"),     # Medical Laboratories (LabCorp/Quest)
    "8731": ("Healthcare", "Biotechnology"),              # Commercial Physical & Biological Research

    # --- Financial ---
    "6021": ("Financial", "Banks"),                       # National Commercial Banks
    "6022": ("Financial", "Banks"),                       # State Commercial Banks
    "6199": ("Financial", "Capital Markets"),             # (finance services, reserved)
    "6200": ("Financial", "Capital Markets"),             # Security & Commodity Brokers
    "6211": ("Financial", "Capital Markets"),             # Security Brokers Dealers
    "6282": ("Financial", "Asset Management"),            # Investment Advice (BlackRock)
    "6311": ("Financial", "Insurance - Life"),            # Life Insurance
    "6331": ("Financial", "Insurance - Property & Casualty"),  # Fire Marine & Casualty Insurance
    "6399": ("Financial", "Insurance - Diversified"),     # Insurance Carriers NEC
    "6411": ("Financial", "Insurance Brokers"),           # Insurance Agents Brokers

    # --- Real Estate ---
    "6510": ("Real Estate", "Real Estate - Services"),    # Real Estate Operators & Lessors
    "6798": ("Real Estate", "REIT"),                      # Real Estate Investment Trusts (REIT)

    # --- Communication Services ---
    "3663": ("Communication Services", "Broadcasting"),   # Radio & TV Broadcasting Equipment
    "4841": ("Communication Services", "Telecom Services"),  # Cable & Other Pay Television
    "7311": ("Communication Services", "Advertising Agencies"),  # Services-Advertising Agencies

    # --- Technology ---
    "3570": ("Technology", "Computer Hardware"),          # Computer & Office Equipment
    "3571": ("Technology", "Consumer Electronics"),       # Electronic Computers (Apple)
    "3572": ("Technology", "Computer Hardware"),          # Computer Storage Devices
    "3576": ("Technology", "Communication Equipment"),    # Computer Communications Equipment
    "3577": ("Technology", "Computer Hardware"),          # Computer Peripheral Equipment
    "3661": ("Technology", "Communication Equipment"),    # Telephone & Telegraph Apparatus
    "3669": ("Technology", "Communication Equipment"),    # Communications Equipment NEC
    "3672": ("Technology", "Electronic Components"),       # Printed Circuit Boards
    "3674": ("Technology", "Semiconductors"),             # Semiconductors & Related Devices
    "3823": ("Technology", "Scientific & Technical Instruments"),  # Industrial Instruments
    "3825": ("Technology", "Scientific & Technical Instruments"),  # Instruments Measuring Electricity
    "3829": ("Technology", "Scientific & Technical Instruments"),  # Measuring & Controlling NEC
    "7370": ("Technology", "Information Technology Services"),  # Computer Programming Data Processing
    "7371": ("Technology", "Information Technology Services"),  # Computer Programming Services
    "7372": ("Technology", "Software"),                   # Prepackaged Software (Microsoft, Adobe)
    "7373": ("Technology", "Information Technology Services"),  # Computer Integrated Systems Design
    "7374": ("Technology", "Information Technology Services"),  # Computer Processing & Data Prep

    # --- Industrials ---
    "1600": ("Industrials", "Engineering & Construction"),  # Heavy Construction
    "1731": ("Industrials", "Engineering & Construction"),  # Electrical Work
    "3411": ("Consumer Cyclical", "Packaging & Containers"),  # Metal Cans
    "3420": ("Industrials", "Tools & Accessories"),       # Cutlery Handtools Hardware
    "3430": ("Industrials", "Building Products & Equipment"),  # Heating Equip Plumbing Fixtures
    "3490": ("Industrials", "Metal Fabrication"),         # Fabricated Metal Products
    "3523": ("Industrials", "Farm & Heavy Construction Machinery"),  # Farm Machinery & Equipment
    "3531": ("Industrials", "Farm & Heavy Construction Machinery"),  # Construction Machinery (CAT)
    "3550": ("Industrials", "Specialty Industrial Machinery"),  # Special Industry Machinery
    "3559": ("Industrials", "Specialty Industrial Machinery"),  # Special Industry Machinery NEC
    "3560": ("Industrials", "Specialty Industrial Machinery"),  # General Industrial Machinery
    "3561": ("Industrials", "Specialty Industrial Machinery"),  # Pumps & Pumping Equipment
    "3569": ("Industrials", "Specialty Industrial Machinery"),  # General Industrial Machinery NEC
    "3585": ("Industrials", "Building Products & Equipment"),  # Air-Cond & Refrigeration Equip
    "3590": ("Industrials", "Specialty Industrial Machinery"),  # Misc Industrial Machinery
    "3600": ("Industrials", "Electrical Equipment & Parts"),  # Electronic & Other Electrical Equip
    "3621": ("Industrials", "Electrical Equipment & Parts"),  # Motors & Generators
    "3720": ("Industrials", "Aerospace & Defense"),       # Aircraft & Parts
    "3724": ("Industrials", "Aerospace & Defense"),       # Aircraft Engines
    "3730": ("Industrials", "Aerospace & Defense"),       # Ship & Boat Building
    "3812": ("Industrials", "Aerospace & Defense"),       # Search Detection Navigation (defense)
    "3826": ("Healthcare", "Diagnostics & Research"),     # Laboratory Analytical Instruments (Thermo)
    "4011": ("Industrials", "Railroads"),                 # Railroads
    "4210": ("Industrials", "Trucking"),                  # Trucking & Courier Services
    "4400": ("Industrials", "Marine Shipping"),           # Water Transportation
    "4512": ("Industrials", "Airlines"),                  # Air Transportation Scheduled
    "4513": ("Industrials", "Integrated Freight & Logistics"),  # Air Courier Services (FedEx)
    "4700": ("Industrials", "Integrated Freight & Logistics"),  # Transportation Services
    "4731": ("Industrials", "Integrated Freight & Logistics"),  # Arrangement of Freight Transport
    "4953": ("Industrials", "Waste Management"),          # Refuse Systems (Waste Mgmt/Republic)
    "7320": ("Industrials", "Consulting Services"),       # Services-Consumer Credit Reporting
    "7340": ("Industrials", "Specialty Business Services"),  # Services-To Dwellings & Buildings
    "7389": ("Industrials", "Specialty Business Services"),  # Services-Business Services NEC
    "8700": ("Industrials", "Consulting Services"),       # Engineering Accounting Research Mgmt

    # --- Utilities ---
    "4911": ("Utilities", "Utilities-Regulated Electric"),  # Electric Services
    "4931": ("Utilities", "Utilities-Regulated Electric"),  # Electric & Other Services Combined
    "4991": ("Utilities", "Utilities-Independent Power Producers"),  # Cogeneration Services
}


# English canonical sector name -> Korean label.
SECTOR_KO: dict[str, str] = {
    "Technology": "기술",
    "Healthcare": "헬스케어",
    "Financial": "금융",
    "Consumer Cyclical": "경기소비재",
    "Consumer Defensive": "필수소비재",
    "Communication Services": "커뮤니케이션",
    "Industrials": "산업재",
    "Energy": "에너지",
    "Basic Materials": "소재",
    "Real Estate": "부동산",
    "Utilities": "유틸리티",
}


# Coarse 2-digit SIC major-group -> canonical English sector, for codes not in SIC_MAP.
# Deliberately approximate ("reasonable guess"): every code we actually observe is in
# SIC_MAP, so this only guards genuinely unseen codes.
_PREFIX_SECTOR: dict[str, str] = {
    "01": "Consumer Defensive", "02": "Consumer Defensive",  # agriculture
    "07": "Consumer Defensive", "08": "Basic Materials", "09": "Basic Materials",
    "10": "Basic Materials", "12": "Basic Materials", "14": "Basic Materials",  # mining
    "13": "Energy", "29": "Energy",                          # oil & gas
    "15": "Industrials", "16": "Industrials", "17": "Industrials",  # construction
    "20": "Consumer Defensive", "21": "Consumer Defensive",  # food/tobacco
    "22": "Consumer Cyclical", "23": "Consumer Cyclical",    # textiles/apparel
    "24": "Basic Materials", "25": "Consumer Cyclical", "26": "Basic Materials",
    "27": "Communication Services",                          # printing/publishing
    "28": "Basic Materials",                                 # chemicals (default; pharma is explicit)
    "30": "Consumer Cyclical", "31": "Consumer Cyclical",
    "32": "Basic Materials", "33": "Basic Materials", "34": "Industrials",
    "35": "Industrials", "36": "Technology", "37": "Industrials",
    "38": "Technology", "39": "Consumer Cyclical",           # instruments / misc mfg
    "40": "Industrials", "41": "Industrials", "42": "Industrials",
    "44": "Industrials", "45": "Industrials", "47": "Industrials",  # transportation
    "48": "Communication Services",                          # communications
    "49": "Utilities",                                       # utilities
    "50": "Consumer Cyclical", "51": "Consumer Defensive",   # wholesale
    "52": "Consumer Cyclical", "53": "Consumer Cyclical", "54": "Consumer Defensive",
    "55": "Consumer Cyclical", "56": "Consumer Cyclical", "57": "Consumer Cyclical",
    "58": "Consumer Cyclical", "59": "Consumer Cyclical",    # retail
    "60": "Financial", "61": "Financial", "62": "Financial", "63": "Financial",
    "64": "Financial", "65": "Real Estate", "67": "Financial",  # finance / real estate
    "70": "Consumer Cyclical", "72": "Consumer Cyclical", "73": "Technology",
    "78": "Communication Services", "79": "Consumer Cyclical",
    "80": "Healthcare", "82": "Consumer Defensive", "87": "Industrials",
}


def classify(sic) -> tuple[str, str, str]:
    """Classify a SEC SIC code into (sector_ko, industry_en, sector_en).

    1. Exact 4-digit lookup in SIC_MAP (authoritative, finviz-aligned).
    2. Fallback by 2-digit SIC major group -> a reasonable sector guess; the industry
       is reported as the English sector name (we have no finer signal for unseen codes).
    3. Anything unrecognized (incl. None/empty) -> ("기타", "Other", "Other").
    """
    if sic is None:
        return ("기타", "Other", "Other")
    code = str(sic).strip()
    if not code:
        return ("기타", "Other", "Other")

    hit = SIC_MAP.get(code)
    if hit is not None:
        sector_en, industry_en = hit
        return (SECTOR_KO[sector_en], industry_en, sector_en)

    # 2-digit-prefix fallback
    prefix = code.zfill(4)[:2]
    sector_en = _PREFIX_SECTOR.get(prefix)
    if sector_en is not None:
        return (SECTOR_KO[sector_en], sector_en, sector_en)

    return ("기타", "Other", "Other")


# --------------------------------------------------------------- KR (KSIC → finviz)
# Korean issuers already carry a fine KSIC industry label (전자부품·반도체, 의약품, 금융…).
# We roll those up into the SAME 11 finviz top-level sectors so KR and US share one legend.
# Key = the Korean industry label produced by skg.export.dashboard._ksic_name (KSIC 2-digit).
_KSIC_SECTOR: dict[str, str] = {
    # 기술 Technology
    "전자부품·반도체": "Technology", "의료·정밀기기": "Technology", "소프트웨어": "Technology",
    "정보서비스": "Technology",
    # 헬스케어 Healthcare
    "의약품": "Healthcare", "보건": "Healthcare",
    # 금융 Financial
    "금융": "Financial", "보험": "Financial", "금융지원": "Financial",
    # 경기소비재 Consumer Cyclical (자동차·운송장비·의복·소매·숙박·건설기계 등)
    "자동차": "Consumer Cyclical", "운송장비": "Consumer Cyclical", "의복": "Consumer Cyclical",
    "섬유": "Consumer Cyclical", "소매": "Consumer Cyclical", "가구": "Consumer Cyclical",
    "숙박": "Consumer Cyclical", "음식점": "Consumer Cyclical", "가죽·신발": "Consumer Cyclical",
    "스포츠·여가": "Consumer Cyclical", "개인서비스": "Consumer Cyclical",
    "사업지원서비스": "Consumer Cyclical",
    # 필수소비재 Consumer Defensive
    "식료품": "Consumer Defensive", "음료": "Consumer Defensive", "도매": "Consumer Defensive",
    # 커뮤니케이션 Communication Services
    "통신": "Communication Services", "출판": "Communication Services",
    "영상·방송": "Communication Services", "예술": "Communication Services",
    # 산업재 Industrials (기계·전기장비·건설·운송·항공·조선 등)
    "기계·장비": "Industrials", "전기장비": "Industrials", "건설": "Industrials",
    "토목": "Industrials", "육상운송": "Industrials", "수상운송": "Industrials",
    "항공운송": "Industrials", "창고·운송지원": "Industrials", "금속가공": "Industrials",
    "1차금속": "Industrials", "전문서비스": "Industrials", "건축·엔지니어링": "Industrials",
    "연구개발": "Industrials", "기타전문": "Industrials", "폐기물": "Industrials",
    # 에너지 Energy
    "석유정제": "Energy", "원유·가스": "Energy",
    # 소재 Basic Materials
    "화학": "Basic Materials", "고무·플라스틱": "Basic Materials", "펄프·종이": "Basic Materials",
    "비금속광물": "Basic Materials", "금속광업": "Basic Materials", "목재": "Basic Materials",
    "인쇄": "Basic Materials",
    # 부동산 Real Estate
    "부동산": "Real Estate",
    # 유틸리티 Utilities
    "전기·가스": "Utilities", "수도": "Utilities",
}


def classify_ksic(industry_ko: str) -> tuple[str, str, str]:
    """KR: (sector_ko, industry_ko, sector_en) from the Korean KSIC industry label.
    The fine KR label is kept AS the industry (industry-level detail); the top-level
    sector is the finviz roll-up so both markets share one legend."""
    ind = (industry_ko or "").strip()
    sector_en = _KSIC_SECTOR.get(ind)
    if sector_en is None:
        return ("기타", ind or "Other", "Other")
    return (SECTOR_KO[sector_en], ind, sector_en)
