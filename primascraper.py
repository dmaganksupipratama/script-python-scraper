import os
import json
import time
import random
import zipfile
import shutil
import re
import pandas as pd
from curl_cffi import requests

def log_message(log_file, msg):
    """Print to console in real-time and write to a persistent log file."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(formatted_msg + "\n")

def fetch_audit_metadata(year, session, log_file):
    """Fetch 100% of audit (Q4) metadata for the given year in a single request."""
    url = "https://idx.co.id/primary/ListedCompany/GetFinancialReport"
    params = {
        'indexFrom': 1,
        'pageSize': 2500,  # Large page size to get all company audits in one go
        'year': year,
        'reportType': 'rdf',  # rdf = financial statement (which contains both FS and Annual Report attachments)
        'EmitenType': 's',
        'periode': 'audit',   # Focus only on Q4 Audit
        'kodeEmiten': '',     # Empty means all companies
        'SortColumn': 'KodeEmiten',
        'SortOrder': 'asc'
    }
    
    log_message(log_file, f"Pre-fetching 2025 Q4 Audit metadata from IDX...")
    try:
        r = session.get(url, params=params, impersonate="chrome", timeout=45)
        if r.status_code == 200:
            data = r.json()
            results = data.get("Results", [])
            log_message(log_file, f"  --> Successfully retrieved metadata for {len(results)} companies.")
            return results
        else:
            log_message(log_file, f"  --> Failed with status code: {r.status_code}. Response: {r.text[:300]}")
            return []
    except Exception as e:
        log_message(log_file, f"  --> Error fetching metadata: {e}")
        return []

def download_file(url, save_path, session, log_file):
    """Download a binary file from IDX with a retry mechanism."""
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            r = session.get(url, impersonate="chrome", timeout=60)
            if r.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                return True
            else:
                log_message(log_file, f"      [Attempt {attempt}/{max_retries}] Download failed for {url}. Status: {r.status_code}")
        except Exception as e:
            log_message(log_file, f"      [Attempt {attempt}/{max_retries}] Download error: {e}")
        time.sleep(2.0)
    return False

def main():
    start_time = time.time()  # Start tracking execution time
    
    target_year = '2025'
    q_period = 'Q4'
    base_dir = os.getcwd()
    csv_path = os.path.join(base_dir, "companies.csv")
    log_file = os.path.join(base_dir, "scraper_run.log")
    state_file = os.path.join(base_dir, "scraper_state.json")
    temp_dir = os.path.join(base_dir, "temp_idx_download")
    final_zip_path = os.path.join(base_dir, "Financial_Statement_2025.zip")
    
    # Initialize Log File
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("=== IDX FINANCIAL STATEMENT & ANNUAL REPORT SCRAPER 2025 (Q4 Audit Only) ===\n")
    log_message(log_file, "Initializing Scraper...")
    
    # 1. Load Company List from CSV
    if not os.path.exists(csv_path):
        log_message(log_file, f"CRITICAL ERROR: Company CSV not found at {csv_path}!")
        return
    
    try:
        df = pd.read_csv(csv_path)
        tickers = df['Kode'].dropna().str.strip().str.upper().unique().tolist()
        log_message(log_file, f"Successfully loaded {len(tickers)} company tickers from CSV.")
    except Exception as e:
        log_message(log_file, f"CRITICAL ERROR reading CSV: {e}")
        return
        
    # 2. Load Checkpoint State
    processed_tickers = set()
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                processed_list = json.load(f)
                processed_tickers = set(processed_list)
                log_message(log_file, f"Found existing checkpoint. {len(processed_tickers)} tickers already completed. Resuming...")
        except Exception as e:
            log_message(log_file, f"Warning reading state file: {e}. Starting fresh.")
            
    # 3. Create Session & Fetch 100% of 2025 Q4 Audit Metadata
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan/'
    })
    
    audit_results = fetch_audit_metadata(target_year, session, log_file)
    if not audit_results:
        log_message(log_file, "CRITICAL ERROR: Failed to fetch any audit metadata. Exiting.")
        return
        
    # Index the pre-fetched metadata locally for ultra-fast lookups
    # Map TICKER -> report_object
    local_meta_index = {}
    for r in audit_results:
        ticker = r.get("KodeEmiten")
        if ticker:
            local_meta_index[ticker.upper().strip()] = r
            
    log_message(log_file, f"Pre-indexing complete! {len(local_meta_index)} active audits mapped locally.")
    
    # Create temp directory
    os.makedirs(temp_dir, exist_ok=True)
    
    # Statistics
    total_download_success = 0
    total_download_fails = 0
    total_processed = len(processed_tickers)
    total_targets = len(tickers)
    
    log_message(log_file, "Starting main downloading loop...")
    
    for idx_t, ticker in enumerate(tickers):
        if ticker in processed_tickers:
            continue
            
        log_message(log_file, f"[{idx_t + 1}/{total_targets}] Processing {ticker}...")
        
        if ticker not in local_meta_index:
            log_message(log_file, f"  --> Ticker {ticker} has not uploaded Q4 2025 audit files. Skipping.")
            processed_tickers.add(ticker)
            with open(state_file, 'w') as f:
                json.dump(list(processed_tickers), f)
            continue
            
        report = local_meta_index[ticker]
        attachments = report.get("Attachments", [])
        if not attachments:
            log_message(log_file, f"  --> Ticker {ticker} has no attachments. Skipping.")
            processed_tickers.add(ticker)
            with open(state_file, 'w') as f:
                json.dump(list(processed_tickers), f)
            continue
            
        # Create folder [TICKER]/ inside the temporary download directory
        ticker_folder = os.path.join(temp_dir, ticker)
        os.makedirs(ticker_folder, exist_ok=True)
        
        # Base prefix
        prefix = f"{ticker}_{target_year}_{q_period}_"
        downloaded_any_file = False
        ticker_download_success = 0
        ticker_download_fails = 0
        
        # Download and rename target attachments sequentially (one-by-one)
        for att in attachments:
            file_name = att.get("File_Name", "")
            file_type = att.get("File_Type", "").lower()
            file_path = att.get("File_Path", "")
            
            if not file_path:
                continue
                
            renamed_file = None
            
            # Rule 1: Match XBRL zip (inlineXBRL.zip)
            if file_name == "inlineXBRL.zip":
                renamed_file = f"{prefix}XBRL.zip"
                
            # Rule 2: Match Laporan Tahunan PDF (starts with AnnualReport and is PDF)
            elif file_name.startswith("AnnualReport") and file_type == ".pdf":
                match_main = re.match(r"^AnnualReport\d{4}-[A-Za-z]{4}\.pdf$", file_name, re.IGNORECASE)
                match_att = re.match(r"^AnnualReport\d{4}-[A-Za-z]{4}-att(\d+)\.pdf$", file_name, re.IGNORECASE)
                
                if match_main:
                    renamed_file = f"{prefix}AnnualReport.pdf"
                elif match_att:
                    att_num = match_att.group(1)
                    renamed_file = f"{prefix}AnnualReport_att{att_num}.pdf"
                else:
                    renamed_file = f"{prefix}{file_name}"
            
            # Download file if matched (one-by-one)
            if renamed_file:
                save_path = os.path.join(ticker_folder, renamed_file)
                if not os.path.exists(save_path):
                    url = "https://idx.co.id" + file_path
                    log_message(log_file, f"    Downloading: '{file_name}' as '{renamed_file}'...")
                    if download_file(url, save_path, session, log_file):
                        ticker_download_success += 1
                        downloaded_any_file = True
                        # Sub-delay between files of the same company (one-by-one)
                        time.sleep(1.0)
                    else:
                        ticker_download_fails += 1
                else:
                    ticker_download_success += 1 # Already exists
                    
        # Sleep politely between companies
        if downloaded_any_file:
            sleep_time = random.uniform(1.5, 3.5)
            log_message(log_file, f"  --> Completed downloads for {ticker} ({ticker_download_success} files). Sleeping for {sleep_time:.2f}s...")
            time.sleep(sleep_time)
        else:
            log_message(log_file, f"  --> No new files downloaded for {ticker}. Continuing...")
            
        total_download_success += ticker_download_success
        total_download_fails += ticker_download_fails
        
        # Save progress checkpoint
        processed_tickers.add(ticker)
        with open(state_file, 'w') as f:
            json.dump(list(processed_tickers), f)
            
    # 4. Final Zipping Phase
    log_message(log_file, "All tickers processed! Initiating compression...")
    if os.path.exists(temp_dir) and any(os.scandir(temp_dir)):
        try:
            log_message(log_file, f"Compressing folder '{temp_dir}' to '{final_zip_path}'...")
            with zipfile.ZipFile(final_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Archive structure: [TICKER]/[renamed_file]
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
                        
            log_message(log_file, "ZIP file created successfully!")
            
            # Clean up temporary folder
            log_message(log_file, "Cleaning up temporary folder...")
            shutil.rmtree(temp_dir)
            log_message(log_file, "Cleanup completed successfully.")
            
            # Delete state file since we are finished
            if os.path.exists(state_file):
                os.remove(state_file)
                
        except Exception as e:
            log_message(log_file, f"Error during zipping or cleanup: {e}")
    else:
        log_message(log_file, "Warning: No files were downloaded. Final ZIP file not created.")
        
    # Calculate execution time
    end_time = time.time()
    elapsed_seconds = end_time - start_time
    elapsed_minutes = int(elapsed_seconds // 60)
    elapsed_remaining_seconds = int(elapsed_seconds % 60)
    
    log_message(log_file, "=== SCRAPING SESSION FINISHED ===")
    log_message(log_file, f"Total successful file downloads: {total_download_success}")
    log_message(log_file, f"Total file download failures: {total_download_fails}")
    log_message(log_file, f"Total execution time: {elapsed_minutes} minutes and {elapsed_remaining_seconds} seconds ({elapsed_seconds:.2f} seconds).")

if __name__ == "__main__":
    main()
