"""Built-in merchant keywords → default category names.

These give instant, free, offline categorization for common merchants (UK + US).
User rules always win over these; the LLM handles whatever is left.
"""

from __future__ import annotations

# fmt: off
KEYWORDS: dict[str, list[str]] = {
    "Sales": [
        "sumup", "square", "sq *payout", "zettle", "izettle", "stripe payout", "stripe transfer",
        "shopify payout", "paypal payout", "card sales", "clover", "toast payout", "etsy deposit",
        "amazon payments", "uber eats payout", "deliveroo payout", "just eat payout",
    ],
    "Services Income": ["invoice payment", "client payment", "upwork", "fiverr", "toptal"],
    "Interest Income": ["interest paid", "gross interest", "credit interest", "interest earned"],
    "Cost of Goods Sold": [
        "bookers", "booker", "costco", "makro", "brakes", "sysco", "us foods", "bidfood",
        "jj foodservice", "restaurant depot", "wholesale", "cash and carry", "alibaba",
    ],
    "Rent": ["rent", "lease payment", "landlord", "wework", "regus"],
    "Utilities": [
        "british gas", "edf", "octopus energy", "eon", "e.on", "ovo energy", "thames water",
        "severn trent", "anglian water", "con edison", "pg&e", "duke energy", "pseg",
        "national grid", "electricity", "water bill", "gas bill",
    ],
    "Payroll": ["hmrc paye", "payroll", "salary", "salaries", "wages", "gusto", "adp", "paychex", "deel"],
    "Software & Subscriptions": [
        "adobe", "microsoft", "google workspace", "gsuite", "google cloud", "slack", "notion",
        "zoom", "dropbox", "github", "aws", "amazon web services", "shopify subscription",
        "canva", "xero", "quickbooks", "intuit", "openai", "anthropic", "atlassian", "figma",
        "hubspot", "mailchimp", "squarespace", "wix", "godaddy", "netlify", "vercel",
    ],
    "Marketing & Advertising": [
        "facebook ads", "facebk", "meta ads", "google ads", "linkedin ads", "tiktok ads",
        "instagram ads", "yelp ads", "vistaprint", "moo print",
    ],
    "Office Supplies": ["staples", "ryman", "office depot", "officemax", "viking direct"],
    "Equipment": ["currys", "apple store", "best buy", "dell", "lenovo", "ikea"],
    "Travel": [
        "uber", "lyft", "bolt", "trainline", "tfl", "amtrak", "ryanair", "easyjet",
        "british airways", "delta air", "united airlines", "american airlines", "airbnb",
        "booking.com", "expedia", "premier inn", "travelodge", "marriott", "hilton",
    ],
    "Vehicle & Fuel": [
        "shell", "bp", "esso", "texaco", "chevron", "exxon", "fuel", "petrol", "parking",
        "ringgo", "paybyphone", "dvla", "kwik fit",
    ],
    "Meals & Entertainment": [
        "uber eats", "deliveroo", "just eat", "doordash", "grubhub", "starbucks", "pret",
        "costa coffee", "mcdonalds", "restaurant",
    ],
    "Telephone & Internet": [
        "bt group", "bt broadband", "vodafone", "ee limited", "o2", "virgin media", "sky digital",
        "verizon", "at&t", "t-mobile", "comcast", "xfinity", "spectrum",
    ],
    "Insurance": ["insurance", "aviva", "axa", "hiscox", "simply business", "direct line", "geico"],
    "Professional Fees": ["accountant", "accountancy", "solicitor", "legal fees", "lawyer", "legalzoom"],
    "Bank Fees": [
        "bank charge", "account fee", "monthly fee", "overdraft fee", "service charge",
        "transaction fee", "interest charged", "stripe fee", "paypal fee",
    ],
    "Shipping & Postage": [
        "royal mail", "dhl", "fedex", "ups", "usps", "parcelforce", "evri", "hermes", "dpd",
    ],
    "Repairs & Maintenance": ["plumber", "electrician", "repair", "maintenance", "screwfix", "toolstation"],
    "Taxes & Licenses": [
        "hmrc", "irs", "council tax", "business rates", "vat payment", "corporation tax",
        "companies house", "licence fee", "license fee", "franchise tax",
    ],
    "Training": ["udemy", "coursera", "linkedin learning", "pluralsight"],
    "Transfers": ["transfer to", "transfer from", "to savings", "from savings", "internal transfer"],
    "Owner Drawings": ["owner draw", "drawings", "dividend"],
    "Loan": ["loan repayment", "loan payment", "funding circle", "iwoca", "loan advance"],
}
# fmt: on
