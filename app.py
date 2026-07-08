import streamlit as st
import pandas as pd

# 1. Main Page Configurations
st.set_page_config(page_title="IDX Financial Dashboard", layout="wide", page_icon="📊")

st.title("📊 IDX Financial Statement Dashboard")
st.markdown("---")

# 2. Establish connection to Supabase PostgreSQL using secrets.toml configuration
try:
    conn = st.connection("postgresql", type="sql")
    # Fetch data sorted by year descending
    df_raw = conn.query("SELECT * FROM extracted_financials ORDER BY year DESC;", ttl="10m")
except Exception as e:
    st.error(f"Gagal menghubungkan ke database Supabase: {e}")
    st.info("Pastikan database Supabase Anda aktif dan kredensial di `.streamlit/secrets.toml` sudah benar.")
    st.stop()

# 3. Create split view layout (1:1)
col_left, col_right = st.columns(2)

# --- LEFT COLUMN: FILTERS & DATASETS ---
with col_left:
    st.subheader("🔍 Filter & Informasi Keuangan")
    
    if df_raw.empty:
        st.warning("Database Supabase Anda masih kosong. Silakan impor data dari CSV terlebih dahulu.")
    else:
        # Dynamic Ticker Selectbox
        unique_tickers = df_raw["ticker"].unique()
        selected_ticker = st.selectbox("Pilih Kode Perusahaan (Ticker):", unique_tickers)
        
        # Filter raw data for the selected ticker
        df_ticker = df_raw[df_raw["ticker"] == selected_ticker]
        min_year = int(df_ticker["year"].min())
        max_year = int(df_ticker["year"].max())
        
        # Get sorted list of available years for the selected ticker
        available_years = sorted(list(df_ticker["year"].unique()), reverse=True)
        
        # Dynamic Year Dropdown (Multiselect)
        selected_years = st.multiselect(
            "Pilih Tahun Laporan:",
            options=available_years,
            default=available_years
        )

        # Filter database records based on selection
        df_filtered = df_ticker[df_ticker["year"].isin(selected_years)].sort_values(by="year", ascending=False)
        
        if df_filtered.empty:
            st.warning("Tidak ada data untuk kombinasi filter ini.")
        else:
            # Display financial report for each year in the range
            for idx, row in df_filtered.iterrows():
                year = row["year"]
                currency = row["currency"]
                company_name = row["company_name"]
                
                st.markdown(f"### 📅 Laporan Keuangan Tahun {year}")
                
                # Number formatting helper
                def fmt(val):
                    if pd.isna(val) or val is None:
                        return "-"
                    return f"{currency} {val:,.2f}"

                # Expander 1: Profil Perusahaan
                with st.expander(f"🏷️ Profil Perusahaan ({company_name})", expanded=True):
                    st.write(f"**Nama Perusahaan:** {company_name}")
                    st.write(f"**Ticker:** {selected_ticker}")
                    st.write(f"**Mata Uang Laporan:** {currency}")
                    st.write(f"**Tahun Laporan:** {year}")
                
                # Expander 2: Laporan Laba Rugi
                with st.expander("📈 Laporan Laba Rugi (Income Statement)", expanded=True):
                    st.metric(label="Revenue (Pendapatan)", value=fmt(row["revenue"]))
                    st.write(f"**COGS (Beban Pokok Pendapatan):** {fmt(row['cogs'])}")
                    st.write(f"**Gross Profit (Laba Kotor):** {fmt(row['gross_profit'])}")
                    st.write(f"**Selling Expense (Beban Penjualan):** {fmt(row['selling_expense'])}")
                    st.write(f"**General Expense (Beban Umum):** {fmt(row['general_expense'])}")
                    st.write(f"**Administrative Expense (Beban Administrasi):** {fmt(row['administrative_expense'])}")
                    st.write(f"**Pretax Income (Laba Sebelum Pajak):** {fmt(row['pretax_income'])}")
                    st.write(f"**Current Income Tax (Beban Pajak Kini):** {fmt(row['current_income_tax'])}")
                    st.write(f"**Net Income (Laba Bersih):** {fmt(row['net_income'])}")
                    
                # Expander 3: Neraca & Arus Kas
                with st.expander("📊 Neraca & Arus Kas (Balance Sheet & Cash Flow)", expanded=True):
                    st.write(f"**Total Assets (Total Aset):** {fmt(row['total_assets'])}")
                    st.write(f"**Total Debt (Total Liabilitas/Utang):** {fmt(row['total_debt'])}")
                    st.write(f"**Accounts Receivable (Piutang Usaha):** {fmt(row['accounts_receivable'])}")
                    st.write(f"**Inventory (Persediaan):** {fmt(row['inventory'])}")
                    st.write(f"**PPE (Aset Tetap/Properti & Peralatan):** {fmt(row['ppe'])}")
                    st.write(f"**Intangible Assets (Aset Takberwujud):** {fmt(row['intangible_assets'])}")
                    st.write(f"**Operating Cash Flow (Arus Kas Operasional):** {fmt(row['operating_cash_flow'])}")
                    st.write(f"**Total Accrual:** {fmt(row['total_accrual'])}")
                
                st.markdown("---")

# --- RIGHT COLUMN: EMPTY PANEL ---
with col_right:
    st.subheader("📈 Analisis Visual (Dicadangkan)")
    st.info(
        "Panel kanan ini dicadangkan untuk visualisasi grafik tren keuangan, "
        "analisis rasio (seperti NPM, DER, ROA), atau perbandingan multi-perusahaan di masa depan."
    )
