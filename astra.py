import streamlit as st
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, text

# --- CONFIG ---
st.set_page_config(page_title="ASTRA - Intelligent Space Allocator", layout="wide")

# --- DATABASE CONNECTION ---
# Pastikan URL ini sudah kamu masukkan di Streamlit Secrets (Dashboard Streamlit Cloud)
def get_engine():
    try:
        # Mengambil URL dari st.secrets
        conn_url = st.secrets["connections"]["postgresql"]["url"]
        return create_engine(conn_url)
    except Exception as e:
        st.error(f"Koneksi Database Gagal: {e}")
        return None

engine = get_engine()

# --- FUNGSI DATABASE ---
def load_data(query):
    with engine.connect() as conn:
        return pd.read_sql(query, conn)

def execute_query(query, params):
    with engine.begin() as conn:
        conn.execute(text(query), params)

# --- AUTH SYSTEM (Simple) ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.username = None

def login():
    st.title("🔐 ASTRA Login System")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        user = st.text_input("Username")
        pwd = st.text_input("Password", type="password")
        role = st.selectbox("Login Sebagai", ["Mahasiswa", "Staff Akademik", "Wakil Dekan 3"])
        if st.button("Masuk Aplikasi"):
            if user and pwd:
                st.session_state.logged_in = True
                st.session_state.role = role
                st.session_state.username = user
                st.rerun()

# --- SISCER LOGIC (SAW + COLLISION) ---
def run_saw_recommendation(peserta, tgl, mulai, selesai):
    # 1. Load Data
    df_ruangan = load_data("SELECT * FROM master_ruangan")
    # Cek bentrok (Collision Detection)
    query_bentrok = """
        SELECT ruangan_id FROM transaksi_peminjaman 
        WHERE tanggal = :tgl AND status_aju != 'Ditolak'
        AND NOT (jam_selesai <= :mulai OR jam_mulai >= :selesai)
    """
    df_bentrok = load_data(text(query_bentrok).bindparams(tgl=tgl, mulai=mulai, selesai=selesai))
    booked_ids = df_bentrok['ruangan_id'].tolist()
    
    available = df_ruangan[~df_ruangan['id'].isin(booked_ids)].copy()
    if available.empty: return None

    # 2. SAW Logic
    W = [0.6, 0.4] # Bobot Kapasitas & Fasilitas
    available['n_kap'] = available['kapasitas'] / available['kapasitas'].max()
    available['n_fas'] = available['fasilitas'] / available['fasilitas'].max()
    available['skor'] = (available['n_kap'] * W[0]) + (available['n_fas'] * W[1])
    
    return available.sort_values(by='skor', ascending=False)

# --- PAGES ---
def page_mahasiswa():
    st.title(f"👋 Halo, {st.session_state.username}")
    tab1, tab2 = st.tabs(["🆕 Ajukan Peminjaman", "📜 Riwayat Saya"])
    
    with tab1:
        st.subheader("Form Reservasi Cerdas")
        col1, col2 = st.columns(2)
        with col1:
            nama_kgt = st.text_input("Nama Kegiatan")
            tgl = st.date_input("Tanggal", min_value=datetime.today())
            peserta = st.number_input("Jumlah Peserta", min_value=1)
        with col2:
            mulai = st.number_input("Jam Mulai", 7, 21, 10)
            selesai = st.number_input("Jam Selesai", 8, 22, 12)
        
        if st.button("Cari Rekomendasi"):
            hasil = run_saw_recommendation(peserta, tgl, mulai, selesai)
            if hasil is not None:
                for _, row in hasil.iterrows():
                    with st.expander(f"📍 {row['nama']} (Skor: {int(row['skor']*100)}%)"):
                        st.write(f"Kapasitas: {row['kapasitas']} | Lokasi: {row['lokasi']}")
                        if st.button("Pilih Ruangan Ini", key=row['id']):
                            query = """
                                INSERT INTO transaksi_peminjaman (username, kegiatan, ruangan_id, tanggal, jam_mulai, jam_selesai, status_aju)
                                VALUES (:u, :k, :rid, :t, :jm, :js, 'Diajukan')
                            """
                            execute_query(query, {"u":st.session_state.username, "k":nama_kgt, "rid":row['id'], "t":tgl, "jm":mulai, "js":selesai})
                            st.success("Berhasil diajukan ke database!")
            else:
                st.error("Semua ruangan bentrok!")

    with tab2:
        st.subheader("Riwayat Peminjaman Anda")
        query = "SELECT t.*, r.nama as nama_ruangan FROM transaksi_peminjaman t JOIN master_ruangan r ON t.ruangan_id = r.id WHERE username = :u"
        df_hist = load_data(text(query).bindparams(u=st.session_state.username))
        st.dataframe(df_hist)

def page_admin():
    st.title(f"⚙️ Panel {st.session_state.role}")
    # Load semua data transaksi
    query = "SELECT t.*, r.nama as nama_ruangan FROM transaksi_peminjaman t JOIN master_ruangan r ON t.ruangan_id = r.id"
    df_all = load_data(query)

    # Filter untuk Akademik (Verifikasi)
    if st.session_state.role == "Staff Akademik":
        st.subheader("Verifikasi Pengajuan Baru")
        pending = df_all[df_all['status_aju'] == 'Diajukan']
        for _, t in pending.iterrows():
            with st.expander(f"{t['kegiatan']} - {t['username']}"):
                if st.button("Verifikasi ✅", key=f"v_{t['id_trans']}"):
                    execute_query("UPDATE transaksi_peminjaman SET status_aju = 'Diverifikasi' WHERE id_trans = :id", {"id":t['id_trans']})
                    st.rerun()

    # Filter untuk WD3 (Approval)
    elif st.session_state.role == "Wakil Dekan 3":
        st.subheader("Approval Akhir")
        verified = df_all[df_all['status_aju'] == 'Diverifikasi']
        for _, t in verified.iterrows():
            with st.expander(f"{t['kegiatan']} - {t['nama_ruangan']}"):
                col_a, col_b = st.columns(2)
                if col_a.button("Setujui", key=f"s_{t['id_trans']}"):
                    execute_query("UPDATE transaksi_peminjaman SET status_aju = 'Disetujui' WHERE id_trans = :id", {"id":t['id_trans']})
                    st.rerun()
                if col_b.button("Tolak", key=f"t_{t['id_trans']}"):
                    execute_query("UPDATE transaksi_peminjaman SET status_aju = 'Ditolak' WHERE id_trans = :id", {"id":t['id_trans']})
                    st.rerun()
    
    st.divider()
    st.write("📊 **Monitoring Transaksi**")
    st.dataframe(df_all)

# --- ROUTING ---
if not st.session_state.logged_in:
    login()
else:
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()
    
    if st.session_state.role == "Mahasiswa":
        page_mahasiswa()
    else:
        page_admin()