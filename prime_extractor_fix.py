import os
import re
import csv
import time
import argparse

# Dynamic Sector-Aware XBRL Mappings (Namespace-free, matching matches of idx-cor:)
SECTOR_MAPPINGS = {
    "General": {
        "Revenue": {"tags": ["SalesAndRevenue", "Revenues", "RevenueFromContractsWithCustomers"], "type": "Duration"},
        "COGS": {"tags": ["CostOfSalesAndRevenue", "CostOfSales", "CostOfRevenues"], "type": "Duration"},
        "Gross_Profit": {"tags": ["GrossProfit"], "type": "Duration"},
        "Selling_Expense": {"tags": ["SellingExpenses"], "type": "Duration"},
        "General_Expense": {"tags": ["GeneralAndAdministrativeExpenses", "GeneralExpenses"], "type": "Duration"},
        "Administrative_Expense": {"tags": ["GeneralAndAdministrativeExpenses", "AdministrativeExpenses"], "type": "Duration"},
        "Pretax_Income": {"tags": ["ProfitLossBeforeIncomeTax", "ProfitLossBeforeTax"], "type": "Duration"},
        "Current_Income_Tax": {"tags": ["CurrentIncomeTaxExpenseBenefit", "CurrentIncomeTaxExpense", "TaxBenefitExpenses", "IncomeTaxExpenseBenefit"], "type": "Duration"},
        "Cash_Tax_Paid": {"tags": ["PaymentsForIncomeTaxesCashFlowsFromUsedInOperatingActivities", "PaymentsForCorporateIncomeTax", "IncomeTaxesRefundedPaidFromOperatingActivities"], "type": "Duration"},
        "Net_Income": {"tags": ["ProfitLoss", "NetIncomeLoss"], "type": "Duration"},
        "Operating_Cash_Flow": {"tags": ["NetCashFlowsFromUsedInOperatingActivities", "NetCashFlowsReceivedFromUsedInOperatingActivities"], "type": "Duration"},
        "Total_Assets": {"tags": ["Assets"], "type": "Instant"},
        "Total_Debt": {"tags": ["Liabilities"], "type": "Instant"},
        "Accounts_Receivable": {"tags": ["TradeAccountsReceivable", "Receivables", "TradeReceivablesThirdParties", "TradeReceivablesRelatedParties"], "type": "Instant"},
        "Inventory": {"tags": ["CurrentInventories", "Inventories"], "type": "Instant"},
        "PPE": {"tags": ["PropertyPlantAndEquipment"], "type": "Instant"},
        "Intangible_Assets": {"tags": ["IntangibleAssetsOtherThanGoodwill", "Goodwill"], "type": "Instant"}
    },
    "Financial": {
        "Revenue": {"tags": ["GrossInterestIncome", "InterestIncome", "PremiumIncome", "Revenues", "SalesAndRevenue"], "type": "Duration"},
        "COGS": {"tags": ["InterestExpenses", "PremiumExpenses", "CostOfSalesAndRevenue"], "type": "Duration"},
        "Gross_Profit": {"tags": ["NetInterestIncome", "NetPremiumIncome", "GrossProfit"], "type": "Duration"},
        "Selling_Expense": {"tags": ["SellingExpenses"], "type": "Duration"}, # usually 0 for banks
        "General_Expense": {"tags": ["GeneralAndAdministrativeExpenses", "GeneralExpenses"], "type": "Duration"},
        "Administrative_Expense": {"tags": ["GeneralAndAdministrativeExpenses", "AdministrativeExpenses"], "type": "Duration"},
        "Pretax_Income": {"tags": ["ProfitLossBeforeIncomeTax", "ProfitLossBeforeTax"], "type": "Duration"},
        "Current_Income_Tax": {"tags": ["CurrentIncomeTaxExpenseBenefit", "CurrentIncomeTaxExpense", "TaxBenefitExpenses", "IncomeTaxExpenseBenefit"], "type": "Duration"},
        "Cash_Tax_Paid": {"tags": ["PaymentsForIncomeTaxesCashFlowsFromUsedInOperatingActivities", "PaymentsForCorporateIncomeTax", "IncomeTaxesRefundedPaidFromOperatingActivities"], "type": "Duration"},
        "Net_Income": {"tags": ["ProfitLoss", "NetIncomeLoss"], "type": "Duration"},
        "Operating_Cash_Flow": {"tags": ["NetCashFlowsFromUsedInOperatingActivities", "NetCashFlowsReceivedFromUsedInOperatingActivities"], "type": "Duration"},
        "Total_Assets": {"tags": ["Assets"], "type": "Instant"},
        "Total_Debt": {"tags": ["Liabilities"], "type": "Instant"},
        "Accounts_Receivable": {"tags": ["TradeAccountsReceivable", "Receivables", "BillsAndOtherReceivablesThirdParties", "BillsAndOtherReceivablesRelatedParties", "TradeReceivablesThirdParties"], "type": "Instant"},
        "Inventory": {"tags": ["CurrentInventories", "Inventories"], "type": "Instant"}, # usually 0 for banks
        "PPE": {"tags": ["PropertyPlantAndEquipment"], "type": "Instant"},
        "Intangible_Assets": {"tags": ["IntangibleAssetsOtherThanGoodwill", "Goodwill"], "type": "Instant"}
    }
}

def parse_xml_val(text_val):
    """Parse numeric values from raw XBRL XML text."""
    if not text_val or text_val.strip() == "-":
        return 0.0
    val_str = text_val.strip()
    is_neg = False
    if val_str.startswith('(') and val_str.endswith(')'):
        is_neg = True
        val_str = val_str[1:-1]
    elif val_str.startswith('-'):
        is_neg = True
        val_str = val_str[1:]
    val_str = val_str.replace(',', '').strip()
    try:
        val = float(val_str)
        return -val if is_neg else val
    except ValueError:
        return 0.0

def parse_instance_xbrl(xml_content, ticker, report_year):
    """Parse raw instance.xbrl content to extract DEI metadata, industry types, and numerical facts."""
    facts = {}  # Map: TagName -> {contextRef: value}
    
    # 1. Parse DEI Metadata using fast regex
    # Matches: <idx-dei:TagName contextRef="Context">Value</idx-dei:TagName>
    dei_pattern = re.compile(r'<(?:[\w-]+:)?(\w+)[^>]*contextRef=["\']([^"\']+)["\'][^>]*>([^<]+)</(?:[\w-]+:)?\1>', re.IGNORECASE)
    
    company_name = ticker
    industry_type = "Umum / General"
    currency_raw = None
    rounding_raw = None
    
    for match in dei_pattern.finditer(xml_content):
        tag, ctx, val = match.groups()
        if tag == "EntityName" and ctx == "CurrentYearInstant":
            company_name = val.strip()
        elif tag == "EntityMainIndustry" and ctx == "CurrentYearInstant":
            industry_type = val.strip()
        elif "PresentationCurrency" in tag and currency_raw is None:
            currency_raw = val.strip()
        elif tag == "LevelOfRoundingUsedInFinancialStatements" and ctx == "CurrentYearInstant":
            rounding_raw = val.strip()

    # Determine Currency code from the raw DEI text (e.g. "Rupiah / IDR")
    currency = "IDR"  # sensible default for IDX filings
    if currency_raw:
        if "Rupiah" in currency_raw or "IDR" in currency_raw:
            currency = "IDR"
        elif "US Dollar" in currency_raw or "USD" in currency_raw:
            currency = "USD"

    # Determine Sector (General vs Financial)
    sector = "General"
    if "Keuangan" in industry_type or "Financial" in industry_type:
        sector = "Financial"

    # 2. Find all <idx-cor:TagName ...>Value</idx-cor:TagName>
    cor_pattern = re.compile(r'<(?:[\w-]+:)?(\w+)[^>]*contextRef=["\']([^"\']+)["\'][^>]*>([^<]+)</(?:[\w-]+:)?\1>', re.IGNORECASE)
    
    for match in cor_pattern.finditer(xml_content):
        tag, ctx, text_val = match.groups()
        val = parse_xml_val(text_val)
        
        if tag not in facts:
            facts[tag] = {}
        facts[tag][ctx] = val
        
    # Determine if values are scaled down in XML
    multiplier = 1.0
    if rounding_raw:
        # Check Assets tag value for CurrentYearInstant to see if it is in thousands or full units
        assets_val = facts.get("Assets", {}).get("CurrentYearInstant", 0.0)
        
        if "Thousand" in rounding_raw or "Ribuan" in rounding_raw:
            # If the assets value is small (e.g. < 50 million), then the numbers are scaled down in XML
            if 0.0 < assets_val < 50000000.0:
                multiplier = 1000.0
                print(f"       [Scaling Detect] '{ticker}' ({report_year}) reported in 'Thousands' and XML contains scaled values. Applying 1,000x multiplier...")
        elif "Million" in rounding_raw or "Jutaan" in rounding_raw:
            # If the assets value is small (e.g. < 50 million), then the numbers are scaled down in XML
            if 0.0 < assets_val < 50000000.0:
                multiplier = 1000000.0
                print(f"       [Scaling Detect] '{ticker}' ({report_year}) reported in 'Millions' and XML contains scaled values. Applying 1,000,000x multiplier...")
        
    # 3. Process into tidy long-format rows (Current Year and Prior Year)
    results = []
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
    
    sector_mapping = SECTOR_MAPPINGS[sector]
    
    for p in periods_def:
        row = {
            "Ticker": ticker,
            "Currency": currency,
            "Company_Name": company_name,
            "Year": p["year"]
        }
        
        # Populate mapped fields based on sector
        for field, config in sector_mapping.items():
            ctx_name = p["instant_ctx"] if config["type"] == "Instant" else p["duration_ctx"]
            field_val = None
            
            # Special logic for Accounts Receivable and Intangible Assets (which includes Goodwill)
            if field in ["Accounts_Receivable", "Intangible_Assets"]:
                sum_val = 0.0
                found_any = False
                for tag in config["tags"]:
                    if tag in facts and ctx_name in facts[tag]:
                        sum_val += facts[tag][ctx_name]
                        found_any = True
                if found_any:
                    field_val = sum_val
            else:
                for tag in config["tags"]:
                    if tag in facts and ctx_name in facts[tag]:
                        field_val = facts[tag][ctx_name]
                        break
                        
            if field_val is not None:
                row[field] = field_val * multiplier
            else:
                row[field] = 0.0
            
        # Post-calculations
        # 1. Gross Profit Fallback (Revenue - COGS)
        if row["Gross_Profit"] == 0.0 and row["Revenue"] != 0.0:
            row["Gross_Profit"] = row["Revenue"] - row["COGS"]

        # 1b. Accounts Receivable Fallback (sum of third-party/related-party sub-accounts)
        if row["Accounts_Receivable"] == 0.0:
            third_party = facts.get("TradeAccountsReceivableThirdParties", {}).get(p["instant_ctx"], 0.0)
            related_party = facts.get("TradeAccountsReceivableRelatedParties", {}).get(p["instant_ctx"], 0.0)
            if third_party or related_party:
                row["Accounts_Receivable"] = (third_party + related_party) * multiplier

        # 2. Total Accrual = Net Income - Operating Cash Flow
        row["Total_Accrual"] = row["Net_Income"] - row["Operating_Cash_Flow"]
        
        results.append(row)
        
    return results

def main():
    parser = argparse.ArgumentParser(description="IDX Financial Statement XBRL Instance Extraction Pipeline")
    parser.add_argument(
        "--input", "-i",
        default=".",
        help="Path to the directory containing flat '{ticker}_Q4_{year}.xbrl' files (default: current directory)."
    )
    parser.add_argument(
        "--output", "-o",
        default="extracted_financials_tidy.csv",
        help="Path to the output CSV file (default: extracted_financials_tidy.csv)."
    )
    parser.add_argument(
        "--delimiter", "-d",
        default=",",
        help="Delimiter for the output CSV file (default: ',')."
    )
    
    args = parser.parse_args()
    
    start_time = time.time()
    input_dir = args.input
    output_csv = args.output
    delimiter = args.delimiter
    
    # 1. Identify all target flat XBRL files in the directory
    if not os.path.isdir(input_dir):
        print(f"Error: Input path '{input_dir}' is not a valid directory.")
        return
    
    xbrl_files = [
        f for f in os.listdir(input_dir)
        if f.lower().endswith(".xbrl") or f.lower().endswith(".xml")
    ]
    
    print(f"Scanning directory '{input_dir}'... Found {len(xbrl_files)} target XBRL/XML files.")
    
    if not xbrl_files:
        print(f"No valid '.xbrl' or '.xml' files found to process in '{input_dir}'.")
        return
        
    print("="*80)
    print("STARTING FINANCIAL STATEMENT INSTANCE.XBRL EXTRACTION PIPELINE")
    print("="*80)
    print(f"Processing {len(xbrl_files)} flat XBRL files (pattern: '{{ticker}}_Q4_{{year}}.xbrl'):")
    for f in xbrl_files:
        print(f"  - {f}")
        
    all_extracted_rows = []
    total_files_parsed = 0
    
    for file_name in xbrl_files:
        file_path = os.path.join(input_dir, file_name)
        
        # 2. Parse ticker and year directly from the strict '{ticker}_Q4_{year}' filename pattern
        name_without_ext = os.path.splitext(file_name)[0]  # e.g., 'AALI_Q4_2021'
        parts = name_without_ext.split('_')
        if len(parts) >= 3:
            ticker = parts[0].upper()
            report_year = parts[2]
        else:
            # Safe regex fallback just in case of slight filename anomalies
            ticker_match = re.search(r'^([A-Z]{4})', name_without_ext)
            year_match = re.search(r'(\d{4})$', name_without_ext)
            ticker = ticker_match.group(1) if ticker_match else "UNKNOWN"
            report_year = year_match.group(1) if year_match else "UNKNOWN"
        
        # Only process odd years (tahun ganjil) to avoid duplicate entries from T and T-1 logic
        try:
            year_val = int(report_year)
            if year_val % 2 == 0:
                print(f"       Skipping even year {report_year} file '{file_name}' to avoid duplicate entries...")
                continue
        except ValueError:
            pass
        
        print(f"\n    -> Parsing Ticker: {ticker} (Report Year: {report_year}) from '{file_name}'...")
        ticker_start = time.time()
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                xml_content = f.read()
                
            company_rows = parse_instance_xbrl(xml_content, ticker, report_year)
            all_extracted_rows.extend(company_rows)
            total_files_parsed += 1
            
            ticker_elapsed = (time.time() - ticker_start) * 1000
            print(f"       Successfully parsed {ticker} in {ticker_elapsed:.2f} ms.")
        except Exception as e:
            print(f"       Error parsing {ticker} ('{file_name}'): {e}")
            
    # Write to CSV
    if all_extracted_rows:
        headers = ["Ticker", "Currency", "Company_Name", "Year"] + list(SECTOR_MAPPINGS["General"].keys()) + ["Total_Accrual"]
        headers_lower = [h.lower() for h in headers]
        
        actual_output_csv = output_csv
        try_suffix = 1
        file_written = False
        
        while not file_written and try_suffix < 20:
            try:
                print(f"\nWriting {len(all_extracted_rows)} tidy rows to {actual_output_csv}...")
                with open(actual_output_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=headers_lower, delimiter=delimiter)
                    writer.writeheader()
                    for r in all_extracted_rows:
                        r_lower = {k.lower(): v for k, v in r.items()}
                        writer.writerow(r_lower)
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
    print(f"Total XBRL Files scanned: {len(xbrl_files)}")
    print(f"Total Companies processed: {total_files_parsed}")
    print(f"Total Rows generated (Long/Tidy format): {len(all_extracted_rows)}")
    print(f"Pipeline Execution Time: {elapsed_seconds:.4f} seconds.")
    print("="*80)

if __name__ == "__main__":
    main()
