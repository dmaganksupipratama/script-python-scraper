import os
import io
import re
import csv
import time
import zipfile

# Configuration for XBRL Taxonomy Tag Mappings with fallback options
XBRL_MAPPINGS = {
    "Revenue": {
        "tags": ["idx-cor:SalesAndRevenue", "idx-cor:Revenues", "idx-cor:RevenueFromContractsWithCustomers", "idx-cor:InterestIncome"],
        "context_type": "Duration"
    },
    "COGS": {
        "tags": ["idx-cor:CostOfSalesAndRevenue", "idx-cor:CostOfSales", "idx-cor:CostOfRevenues", "idx-cor:InterestExpenses"],
        "context_type": "Duration"
    },
    "Gross_Profit": {
        "tags": ["idx-cor:GrossProfit"],
        "context_type": "Duration"
    },
    "Selling_Expense": {
        "tags": ["idx-cor:SellingExpenses"],
        "context_type": "Duration"
    },
    "General_Expense": {
        "tags": ["idx-cor:GeneralAndAdministrativeExpenses", "idx-cor:GeneralExpenses"],
        "context_type": "Duration"
    },
    "Administrative_Expense": {
        "tags": ["idx-cor:GeneralAndAdministrativeExpenses", "idx-cor:AdministrativeExpenses"],
        "context_type": "Duration"
    },
    "Pretax_Income": {
        "tags": ["idx-cor:ProfitLossBeforeIncomeTax"],
        "context_type": "Duration"
    },
    "Current_Income_Tax": {
        "tags": ["idx-cor:TaxBenefitExpenses", "idx-cor:IncomeTaxExpenseBenefit"],
        "context_type": "Duration"
    },
    "Cash_Tax_Paid": {
        "tags": ["idx-cor:PaymentsForCorporateIncomeTax", "idx-cor:IncomeTaxesRefundedPaidFromOperatingActivities"],
        "context_type": "Duration"
    },
    "Net_Income": {
        "tags": ["idx-cor:ProfitLoss", "idx-cor:NetIncomeLoss"],
        "context_type": "Duration"
    },
    "Operating_Cash_Flow": {
        "tags": ["idx-cor:NetCashFlowsReceivedFromUsedInOperatingActivities"],
        "context_type": "Duration"
    },
    "Total_Assets": {
        "tags": ["idx-cor:Assets"],
        "context_type": "Instant"
    },
    "Total_Debt": {
        "tags": ["idx-cor:Liabilities"],
        "context_type": "Instant"
    },
    "Accounts_Receivable": {
        # Will be calculated dynamically as the sum of trade receivables and bank receivables if standard tag isn't there
        "tags": ["idx-cor:TradeReceivablesThirdParties", "idx-cor:BillsAndOtherReceivablesThirdParties"],
        "context_type": "Instant"
    },
    "Inventory": {
        "tags": ["idx-cor:CurrentInventories", "idx-cor:Inventories"],
        "context_type": "Instant"
    },
    "PPE": {
        "tags": ["idx-cor:PropertyPlantAndEquipment"],
        "context_type": "Instant"
    },
    "Intangible_Assets": {
        "tags": ["idx-cor:IntangibleAssetsOtherThanGoodwill"],
        "context_type": "Instant"
    }
}

def parse_non_fraction_val(text_val, scale, is_nil):
    """Parse numeric values from inline XBRL, applying scales and sign rules."""
    if is_nil or not text_val:
        return 0.0
        
    val_str = text_val.strip()
    if val_str == "-" or val_str == "":
        return 0.0
        
    is_negative = False
    if val_str.startswith('(') and val_str.endswith(')'):
        is_negative = True
        val_str = val_str[1:-1]
    elif val_str.startswith('-'):
        is_negative = True
        val_str = val_str[1:]
        
    val_str = val_str.replace(',', '').strip()
    try:
        val = float(val_str)
        if is_negative:
            val = -val
        # Apply scaling (e.g. scale="6" is millions)
        if scale:
            val = val * (10 ** int(scale))
        return val
    except ValueError:
        return 0.0

def extract_from_html(html_content):
    """Parse all numeric and text elements of inline XBRL inside a single HTML file."""
    extracted = {} # format: name -> {contextRef: value}
    entity_name = None
    
    # 1. Parse company name (idx-dei:EntityName)
    # Using lightweight string splits for bulletproof execution across standard Python
    if 'idx-dei:EntityName' in html_content:
        parts = html_content.split('idx-dei:EntityName')
        for p in parts[1:]:
            if '</ix:nonNumeric>' in p:
                name_val = p.split('</ix:nonNumeric>')[0].split('>')[-1].strip()
                if name_val:
                    entity_name = name_val
                    break

    # 2. Find all <ix:nonFraction> tags
    # format: <ix:nonFraction name="idx-cor:Cash" contextRef="CurrentYearInstant" ... scale="6">123,456</ix:nonFraction>
    ix_pattern = re.compile(r'<ix:nonFraction([^>]+)>([^<]*)<\/ix:nonFraction>', re.IGNORECASE)
    
    for match in ix_pattern.finditer(html_content):
        attrs_str, text_val = match.groups()
        
        # Parse attributes
        name_match = re.search(r'name=["\']([^"\']+)["\']', attrs_str)
        ctx_match = re.search(r'contextRef=["\']([^"\']+)["\']', attrs_str)
        scale_match = re.search(r'scale=["\']([^"\']+)["\']', attrs_str)
        nil_match = re.search(r'xsi:nil=["\']true["\']', attrs_str)
        
        if name_match and ctx_match:
            name = name_match.group(1).strip()
            ctx = ctx_match.group(1).strip()
            scale = scale_match.group(1).strip() if scale_match else "0"
            is_nil = True if nil_match else False
            
            val = parse_non_fraction_val(text_val, scale, is_nil)
            
            if name not in extracted:
                extracted[name] = {}
            extracted[name][ctx] = val
            
    return extracted, entity_name

def process_company_xbrl(xbrl_zip_data, ticker, report_year):
    """Processes a single company's extracted XBRL zip in memory."""
    all_extracted = {}
    company_name = ticker # Fallback to ticker
    
    with zipfile.ZipFile(io.BytesIO(xbrl_zip_data), 'r') as x:
        for fname in x.namelist():
            if fname.endswith('.html') or fname.endswith('.htm'):
                html_content = x.read(fname).decode('utf-8', errors='ignore')
                file_data, ent_name = extract_from_html(html_content)
                
                if ent_name:
                    company_name = ent_name
                    
                # Merge into all_extracted
                for k, v_dict in file_data.items():
                    if k not in all_extracted:
                        all_extracted[k] = {}
                    all_extracted[k].update(v_dict)
                    
    # We will extract two rows (Opsi A Tidy/Long format):
    # Row 1: Current Year (2025)
    # Row 2: Prior Year (2024)
    results = []
    
    # Periods to extract
    periods_def = [
        {
            "year": int(report_year),
            "instant_ctx": "CurrentYearInstant",
            "duration_ctx": "CurrentYearDuration"
        },
        {
            "year": int(report_year) - 1,
            "instant_ctx": "PriorEndYearInstant",
            "duration_ctx": "PriorYearDuration"
        }
    ]
    
    for p in periods_def:
        row = {
            "Ticker": ticker,
            "Company_Name": company_name,
            "Year": p["year"]
        }
        
        # Populate each target mapping
        for field, config in XBRL_MAPPINGS.items():
            field_val = None
            ctx_name = p["instant_ctx"] if config["context_type"] == "Instant" else p["duration_ctx"]
            
            # Special logic for Accounts Receivable (Trade + Related + Bills)
            if field == "Accounts_Receivable":
                # Let's sum multiple relevant tags if they exist
                sum_val = 0.0
                found_any = False
                tags_to_sum = [
                    "idx-cor:TradeReceivablesThirdParties",
                    "idx-cor:TradeReceivablesRelatedParties",
                    "idx-cor:BillsAndOtherReceivablesThirdParties",
                    "idx-cor:BillsAndOtherReceivablesRelatedParties"
                ]
                for tag in tags_to_sum:
                    if tag in all_extracted and ctx_name in all_extracted[tag]:
                        sum_val += all_extracted[tag][ctx_name]
                        found_any = True
                if found_any:
                    field_val = sum_val
            else:
                # Standard mapping with fallback search
                for tag in config["tags"]:
                    if tag in all_extracted and ctx_name in all_extracted[tag]:
                        field_val = all_extracted[tag][ctx_name]
                        break # Take the first match
            
            # Default to 0.0 if not found
            row[field] = field_val if field_val is not None else 0.0
            
        # Post-calculations
        # 1. Gross Profit Fallback (Revenue - COGS)
        if row["Gross_Profit"] == 0.0 and row["Revenue"] != 0.0:
            row["Gross_Profit"] = row["Revenue"] - row["COGS"]
            
        # 2. Total Accrual = Net Income - Operating Cash Flow
        row["Total_Accrual"] = row["Net_Income"] - row["Operating_Cash_Flow"]
        
        results.append(row)
        
    return results

import argparse

def main():
    parser = argparse.ArgumentParser(description="IDX Financial Statement XBRL Extraction Pipeline")
    parser.add_argument(
        "--input", "-i",
        default=".",
        help="Path to a single ZIP file (e.g., Financial_Statement_2025_Test_v3.zip) or a directory containing multiple ZIP files (default: current directory)."
    )
    parser.add_argument(
        "--output", "-o",
        default="extracted_financials_tidy.csv",
        help="Path to the output CSV file (default: extracted_financials_tidy.csv)."
    )
    parser.add_argument(
        "--delimiter", "-d",
        default=";",
        help="Delimiter for the output CSV file (default: ';')."
    )
    
    args = parser.parse_args()
    
    start_time = time.time()
    
    input_path = args.input
    output_csv = args.output
    delimiter = args.delimiter
    
    # 1. Identify all target ZIP files
    zip_files = []
    if os.path.isdir(input_path):
        # Scan directory for all ZIP files starting with Financial_Statement_
        for f in os.listdir(input_path):
            if f.endswith(".zip") and f.startswith("Financial_Statement_") and "Test" not in f:
                zip_files.append(os.path.join(input_path, f))
        # If no standard files found, look for any test files too as fallback
        if not zip_files:
            for f in os.listdir(input_path):
                if f.endswith(".zip") and f.startswith("Financial_Statement_"):
                    zip_files.append(os.path.join(input_path, f))
        print(f"Scanning directory '{input_path}'... Found {len(zip_files)} target ZIP files.")
    elif os.path.isfile(input_path) and input_path.endswith(".zip"):
        zip_files.append(input_path)
    else:
        print(f"Error: Input path '{input_path}' is neither a ZIP file nor a valid directory.")
        return
        
    if not zip_files:
        print(f"No valid Financial_Statement_*.zip files found to process in '{input_path}'.")
        return
        
    print("="*80)
    print("STARTING FINANCIAL STATEMENT EXTRACTION PIPELINE (OFFLINE PIPELINE)")
    print("="*80)
    print(f"Reading target definitions from 'dataset.txt'...")
    print(f"Processing {len(zip_files)} ZIP archives:")
    for zf in zip_files:
        print(f"  - {os.path.basename(zf)}")
        
    all_extracted_rows = []
    total_files_parsed = 0
    
    for zf_path in zip_files:
        print(f"\nProcessing Archive: {os.path.basename(zf_path)}...")
        try:
            with zipfile.ZipFile(zf_path, 'r') as main_zip:
                members = main_zip.namelist()
                # Find all company XBRL zip entries (which could be in folders or root)
                xbrl_members = [m for m in members if m.endswith('_XBRL.zip')]
                
                print(f"  Found {len(xbrl_members)} company XBRL filings to parse inside this archive.")
                
                for m_path in xbrl_members:
                    # Ticker is the directory name or prefix of file
                    parts = m_path.split('/')
                    ticker = parts[0] if len(parts) > 1 else m_path.split('_')[0]
                    file_name = parts[-1]
                    
                    # Extract year using regex from the internal company XBRL filename (e.g., AALI_2025_Q4_XBRL.zip)
                    year_match = re.search(r'_(\d{4})_Q\d_XBRL\.zip', file_name)
                    if not year_match:
                        year_match = re.search(r'_(\d{4})_Q4_XBRL\.zip', file_name)
                    if not year_match:
                        year_match = re.search(r'_(\d{4})_', file_name)
                        
                    report_year = year_match.group(1) if year_match else "2025"
                    
                    print(f"    -> Parsing Ticker: {ticker} (Report Year: {report_year})...")
                    ticker_start = time.time()
                    
                    try:
                        xbrl_zip_data = main_zip.read(m_path)
                        company_rows = process_company_xbrl(xbrl_zip_data, ticker, report_year)
                        all_extracted_rows.extend(company_rows)
                        total_files_parsed += 1
                        
                        ticker_elapsed = (time.time() - ticker_start) * 1000
                        print(f"       Successfully parsed {ticker} in {ticker_elapsed:.2f} ms.")
                    except Exception as e:
                        print(f"       Error parsing {ticker}: {e}")
                        
        except Exception as e:
            print(f"  Error reading ZIP archive '{os.path.basename(zf_path)}': {e}")
            
    # Write to CSV
    if all_extracted_rows:
        headers = ["Ticker", "Company_Name", "Year"] + list(XBRL_MAPPINGS.keys()) + ["Total_Accrual"]
        
        # Robust locked-file protection (handles Excel open/lock issues gracefully)
        actual_output_csv = output_csv
        try_suffix = 1
        file_written = False
        
        while not file_written and try_suffix < 20:
            try:
                print(f"\nWriting {len(all_extracted_rows)} tidy rows to {actual_output_csv}...")
                with open(actual_output_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
                    writer.writeheader()
                    for r in all_extracted_rows:
                        writer.writerow(r)
                print(f"CSV file created successfully at: {actual_output_csv}")
                file_written = True
            except PermissionError:
                print(f"  [!] Warning: '{actual_output_csv}' is currently locked (likely open in Excel).")
                actual_output_csv = output_csv.replace(".csv", f"_({try_suffix}).csv")
                try_suffix += 1
            except Exception as e:
                print(f"Error writing CSV file: {e}")
                break
    else:
        print("Warning: No rows were extracted.")
        
    end_time = time.time()
    elapsed_seconds = end_time - start_time
    print("\n" + "="*80)
    print("EXTRACTION COMPLETED SUCCESSFULLY!")
    print("="*80)
    print(f"Total ZIP Archives processed: {len(zip_files)}")
    print(f"Total Companies processed: {total_files_parsed}")
    print(f"Total Rows generated (Long/Tidy format): {len(all_extracted_rows)}")
    print(f"Pipeline Execution Time: {elapsed_seconds:.4f} seconds.")
    print("="*80)

if __name__ == "__main__":
    main()
