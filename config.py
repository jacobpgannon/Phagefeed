"""PhageFeed configuration. Edit freely, then restart the service
(menu: `launchctl kickstart -k gui/$(id -u)/org.phagefeed.server`)."""

# ---------------------------------------------------------------- server
PORT = 8737
REFRESH_SECONDS = 3600          # automatic refresh interval (1 h)
LOOKBACK_DAYS = 60              # window searched on PubMed (entrez date)
BIORXIV_LOOKBACK_DAYS = 60      # bioRxiv window (posting date); one-time backfill ~10-15 min for 60 days
BIORXIV_PARALLEL_DAYS = 3       # bioRxiv days fetched concurrently
BIORXIV_RESCAN_DAYS = 2         # each refresh re-scans the last N days (late postings)
BIORXIV_NEW_VERSIONS = False    # False = only v1 (new preprints), True = also revisions
DEFAULT_PAGE_SIZE = 20          # papers shown before "show more"
FULLTEXT_HIGHLIGHT_SCAN = True  # also scan open-access full text (Europe PMC) for highlight terms

# ---------------------------------------------------------------- journals
# PubMed journal title abbreviations ([ta] field) -> label shown in the app.
# The first block is the list you asked for; the second block is extra journals
# of comparable impact that regularly publish phage / bacterial-immunity work.
JOURNALS = {
    "Cell": "Cell",
    "Nature": "Nature",
    "Science": "Science",
    "Nat Microbiol": "Nature Microbiology",
    "Cell Host Microbe": "Cell Host & Microbe",
    "Mol Cell": "Molecular Cell",
    "EMBO J": "EMBO Journal",
    "EMBO Rep": "EMBO Reports",
    "Nucleic Acids Res": "Nucleic Acids Research",
    "J Bacteriol": "J Bacteriology",
    "Mol Microbiol": "Molecular Microbiology",
    "mBio": "mBio",
    "Proc Natl Acad Sci U S A": "PNAS",
    "Elife": "eLife",
    "Nat Struct Mol Biol": "Nat Struct Mol Biol",
    "Nat Biotechnol": "Nature Biotechnology",
    "Nat Commun": "Nature Communications",
    "Cell Rep": "Cell Reports",
    # --- similar-impact additions -----------------------------------------
    "Sci Adv": "Science Advances",
    "PLoS Biol": "PLOS Biology",
    "PLoS Pathog": "PLOS Pathogens",
    "PLoS Genet": "PLOS Genetics",
    "Curr Biol": "Current Biology",
    "ISME J": "ISME Journal",
    "Nat Chem Biol": "Nature Chemical Biology",
    "Nat Ecol Evol": "Nature Ecology & Evolution",
    "Nat Rev Microbiol": "Nature Reviews Microbiology",
    "Trends Microbiol": "Trends in Microbiology",
    "Annu Rev Microbiol": "Annual Review of Microbiology",
    "Mol Syst Biol": "Molecular Systems Biology",
    "EMBO Mol Med": "EMBO Molecular Medicine",
    "Genes Dev": "Genes & Development",
    "Genome Res": "Genome Research",
    "Cell Syst": "Cell Systems",
    "Cell Genom": "Cell Genomics",
    "Cell Chem Biol": "Cell Chemical Biology",
    "Cell Res": "Cell Research",
    "Structure": "Structure",
    "Nat Methods": "Nature Methods",
    "Nat Genet": "Nature Genetics",
    "Nat Chem": "Nature Chemistry",
    "J Am Chem Soc": "JACS",
    "Mol Biol Evol": "Mol Biol Evol",
    "Microbiome": "Microbiome",
    "Sci Transl Med": "Sci Transl Med",
    "Nat Med": "Nature Medicine",
    "Nat Biomed Eng": "Nat Biomed Eng",
}

# ---------------------------------------------------------------- topic
# PubMed query (title/abstract). Boolean groups are explicitly parenthesised:
# PubMed evaluates operators strictly left to right.
PUBMED_TOPIC = (
    '(phage[tiab] OR phages[tiab] OR bacteriophage*[tiab] OR prophage*[tiab] '
    'OR "anti-phage"[tiab] OR antiphage[tiab] OR mycobacteriophage*[tiab] OR coliphage*[tiab] '
    'OR phageome*[tiab] OR "anti-CRISPR"[tiab] OR "anti-CRISPRs"[tiab] '
    'OR "bacterial immunity"[tiab] OR "bacterial immune"[tiab] '
    'OR "prokaryotic immunity"[tiab] OR "prokaryotic immune"[tiab] '
    'OR ((CRISPR[tiab] OR "defense system"[tiab] OR "defence system"[tiab] '
    'OR "defense systems"[tiab] OR "defence systems"[tiab] OR "abortive infection"[tiab] '
    'OR "restriction-modification"[tiab] OR CBASS[tiab] OR retron*[tiab]) '
    'AND (bacteria*[tiab] OR bacterial[tiab] OR prokaryot*[tiab] OR archaea*[tiab])))'
)

# bioRxiv has no server-side search, so every new preprint is screened locally
# (title + abstract, case-insensitive regexes). A preprint is kept if any
# INCLUDE pattern matches. "macrophage" does not match (word boundary).
INCLUDE_PATTERNS = [
    r"\b(myco|coli|vibrio|cyano|staphylo|archaeo|pro|jumbo|giant)?(bacterio)?phages?\b",
    r"\bphage[-\w]*",
    r"\bphageome",
    r"\banti-?phage",
    r"\banti-?CRISPR",
    r"\b(bacterial|prokaryotic|microbial) (innate |adaptive )?immun",
    r"\b(CBASS|Thoeris|Gabija|Zorya|Septu|Lamassu|Wadjet|BREX|DISARM|Druantia|Hachiman|Kiwa|Shedu|DSR[12]|retrons?|pAgos?|prokaryotic argonautes?|viperins?)\b",
    r"\b(abortive infection|restriction[- ]modification|anti-?viral defen[cs]e system)",
    r"\b(spacer acquisition|CRISPR adaptation|CRISPR(-Cas)? immunity)",
]

# Papers whose only phage connection is a phage-display / PhIP-seq technique
# are dropped unless a phage-biology term also appears.
DISPLAY_PATTERNS = [r"phage[- ]display", r"phage[- ]displayed", r"phage (peptide |antibody )?librar",
                    r"phip-?seq", r"biopanning", r"T7 display", r"M13 display"]
BIOLOGY_PATTERNS = [r"\bbacteriophage", r"\bprophage", r"\blysogen", r"\banti-?phage", r"phage therapy",
                    r"phage infection", r"phage defen[cs]e", r"\bbacterial immun", r"\bhost range",
                    r"\bCRISPR", r"phage (receptor|resistance|predation|replication|genome)"]

# Phrases where a phage appears only as a lab reagent/tool. They are removed
# from bioRxiv text before the INCLUDE test, so a paper that mentions phages
# only this way is skipped.
TOOL_PATTERNS = [r"(bacterio)?phage P1 lox\w*", r"\bP1 lox\w*", r"\bCre[-/]lox\w*",
                 r"(lambda|λ) (bacterio)?phage DNA", r"(bacterio)?phage (lambda|λ) DNA", r"\b(lambda|λ) DNA",
                 r"(lambda|λ)[- ]Red", r"T7 RNA polymerase", r"T7 (promoter|expression)", r"\bphiX ?174 (control|spike)",
                 r"\b(Bxb1|phiC31|φC31)( integrase)?", r"(bacterio)?phage[- ]derived virus[- ]like particles?",
                 r"(bacterio)?phage (virus[- ]like particle|VLP)s?( vaccine)?"]

# Titles that are not research content
EXCLUDE_TITLE_PATTERNS = [r"^(author|publisher)?\s*correction", r"^correction to", r"^erratum",
                          r"^retraction", r"^retracted", r"^expression of concern"]

# ---------------------------------------------------------------- highlights
# Checked in title, abstract and (optionally) open-access full text.
# Clostridioides is included because C. difficile was Clostridium until 2016.
HIGHLIGHTS = [
    {"name": "Listeria", "color": "#d62728", "pattern": r"\bListeria"},
    {"name": "Nostoc/Anabaena", "color": "#2ca02c", "pattern": r"\b(Nostoc|Anabaena)"},
    {"name": "Clostridium", "color": "#8e44ad", "pattern": r"\bClostridi(um|oides|al)\b"},
]

# ---------------------------------------------------------------- AI summary
DEFAULT_SETTINGS = {
    "provider": "anthropic",          # anthropic | ollama | none
    "anthropic_api_key": "",          # or set ANTHROPIC_API_KEY in the environment
    "anthropic_model": "claude-haiku-5-5",
    "ollama_model": "llama3.1",
    "ollama_url": "http://127.0.0.1:11434",
    "unpaywall_email": "",            # optional: improves open-access PDF detection
    "notify": True,                   # macOS notification when new papers arrive
}

SUMMARY_PROMPT = (
    "You are summarizing a new paper for a researcher who studies bacteriophages and "
    "bacterial immune systems. Write exactly two sentences, max ~60 words total: "
    "(1) the key finding, with specific system/organism names; (2) why it matters or the "
    "mechanism. No preamble, no bullet points.\n\nTitle: {title}\nJournal: {journal}\n\n"
    "Abstract: {abstract}"
)
