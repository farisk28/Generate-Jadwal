import streamlit as st
import pandas as pd
import numpy as np
from ortools.sat.python import cp_model
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import io
import datetime

# Setup judul aplikasi
st.set_page_config(page_title="Automated Scheduling System", layout="wide")
st.title("🗓️ Sistem Otomasi Penjadwalan Kerja")
st.write("Upload jadwal bulan lalu untuk membuat jadwal bulan berikutnya secara otomatis sesuai aturan.")

# =====================================================================
# FUNCTION: PARSING JADWAL BULAN LALU (OTOMATIS AMBIL 7 HARI TERAKHIR)
# =====================================================================
def baca_riwayat_bulan_lalu(uploaded_file):
    df = pd.read_excel(uploaded_file, header=None)
    karyawan_list = []
    riwayat_weekly = {}
    
    for idx, row in df.iterrows():
        if idx >= 3 and pd.notna(row[0]) and "Monitoring" in str(row[0]):
            nama_emp = str(row[0]).strip()
            karyawan_list.append(nama_emp)
            
            columns_with_data = []
            for col_idx in range(8, df.shape[1]):
                val_tgl = df.iloc[1, col_idx]
                if pd.notna(val_tgl) and str(val_tgl).isdigit():
                    columns_with_data.append(col_idx)
            
            kolom_7_hari_terakhir = columns_with_data[-7:]
            
            raw_shifts = []
            for col in kolom_7_hari_terakhir:
                val_shift = str(df.iloc[idx, col]).strip()
                if val_shift == '1': raw_shifts.append(1)
                elif val_shift == '2': raw_shifts.append(2)
                elif val_shift == '3': raw_shifts.append(3)
                else: raw_shifts.append(0)
                
            riwayat_weekly[nama_emp] = raw_shifts
            
    bulan_lalu_raw = str(df.iloc[0, 0]).strip()
    if " " in bulan_lalu_raw:
        bulan_lalu_raw = bulan_lalu_raw.split(" ")[0]
        
    date_bulan_lalu = datetime.datetime.strptime(bulan_lalu_raw, "%Y-%m-%d")
    
    return karyawan_list, riwayat_weekly, date_bulan_lalu

# =====================================================================
# INTERFACE STREAMLIT STEP 1 & 2: UPLOAD FILE
# =====================================================================
uploaded_file = st.file_uploader("Pilih file Excel Jadwal Bulan Lalu (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    try:
        karyawan, riwayat_weekly_dict, date_bulan_lalu = baca_riwayat_bulan_lalu(uploaded_file)
        num_karyawan = len(karyawan)
        
        # Buat list riwayat seminggu terakhir yang sinkron berdasarkan nama karyawan
        riwayat_mei_seminggu = [riwayat_weekly_dict[name] for name in karyawan]
        
        if date_bulan_lalu.month == 12:
            thn_depan = date_bulan_lalu.year + 1
            bln_depan = 1
        else:
            thn_depan = date_bulan_lalu.year
            bln_depan = date_bulan_lalu.month + 1
            
        date_bulan_depan = datetime.date(thn_depan, bln_depan, 1)
        
        if bln_depan in [1, 3, 5, 7, 8, 10, 12]: num_hari = 31
        elif bln_depan in [4, 6, 9, 11]: num_hari = 30
        else: num_hari = 29 if thn_depan % 4 == 0 else 28
        
        hari_pertama_idx = date_bulan_depan.weekday()
        nama_hari_format = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
        hari_ke_nama = [nama_hari_format[(hari_pertama_idx + d) % 7] for d in range(num_hari)]
        
        st.success(f"Berhasil membaca data! Menyiapkan jadwal otomatis untuk Bulan: **{date_bulan_depan.strftime('%B %Y')}** ({num_hari} Hari).")
        
        with st.expander("Lihat Karyawan Terdeteksi & Riwayat Akhir Bulan"):
            for i, name in enumerate(karyawan):
                st.write(f"- {name} | Riwayat 7 hari terakhir: {riwayat_mei_seminggu[i]}")

        # =====================================================================
        # STEP 3: TOMBOL GENERATE JADWAL
        # =====================================================================
        if st.button("🚀 Jalankan Otomasi Penjadwalan"):
            with st.spinner("Algoritma sedang menghitung kombinasi terbaik... Mohon tunggu."):
                model = cp_model.CpModel()
                x = {}

                saut_idx = -1
                for idx, name in enumerate(karyawan):
                    if "Saut" in name:
                        saut_idx = idx
                        break

                for i in range(num_karyawan):
                    for d in range(num_hari):
                        if i == 0: # Jasmine hanya boleh Shift 1, Shift 2, atau OFF
                            x[i, d] = model.NewIntVarFromDomain(cp_model.Domain.FromValues([0, 1, 2]), f'x_{i}_{d}')
                        else:
                            x[i, d] = model.NewIntVarFromDomain(cp_model.Domain.FromValues([0, 1, 2, 3]), f'x_{i}_{d}')

                # MATRIKS UTAMA PENANDA HARI LIBUR (is_off_matrix)
                is_off_matrix = {}
                for i in range(num_karyawan):
                    for d in range(num_hari):
                        is_off = model.NewBoolVar(f'is_off_matrix_{i}_{d}')
                        model.Add(x[i, d] == 0).OnlyEnforceIf(is_off)
                        model.Add(x[i, d] != 0).OnlyEnforceIf(is_off.Not())
                        is_off_matrix[i, d] = is_off

                # SYARAT 1: Jatah Libur Bulanan Mutlak (28-30 hari = 8 OFF, 31 hari = 9 OFF)
                if num_hari in [28, 29, 30]:
                    total_off_wajib = 8
                else:
                    total_off_wajib = 9
                
                for i in range(num_karyawan):
                    model.Add(sum(is_off_matrix[i, d] for d in range(num_hari)) == total_off_wajib)

                # SYARAT 4: Setiap Hari yang Libur Wajib 1-2 Orang, Maksimal Toleransi 3 Orang
                for d in range(num_hari):
                    model.Add(sum(is_off_matrix[i, d] for i in range(num_karyawan)) >= 1) 
                    model.Add(sum(is_off_matrix[i, d] for i in range(num_karyawan)) <= 3) 

                # =====================================================================
                # PERBAIKAN BARU: MAKSIMAL LIBUR BERTURUT-TURUT HANYA 3 HARI CEILING (MUTLAK)
                # =====================================================================
                for i in range(num_karyawan):
                    # Ambil status libur 3 hari terakhir dari bulan lalu
                    prev_offs_3d = [1 if s == 0 else 0 for s in riwayat_mei_seminggu[i][-3:]]
                    
                    # Hubungkan dengan variabel libur bulan ini
                    full_off_timeline = prev_offs_3d + [is_off_matrix[i, d] for d in range(num_hari)]
                    
                    # Dalam jendela 4 hari berurutan, tidak boleh semuanya bernilai 1 (OFF) -> Maksimal hanya 3 hari OFF berurutan
                    for start_idx in range(len(full_off_timeline) - 3):
                        window = full_off_timeline[start_idx : start_idx + 4]
                        model.Add(sum(window) <= 3)

                # OPTIMASI PRIORITAS: Menggandengkan Libur Agar Sebisa Mungkin Berurutan (Soft)
                consec_off_vars = []
                for i in range(num_karyawan):
                    for d in range(num_hari - 1):
                        pair_consec = model.NewBoolVar(f'pair_consec_i_{i}_d_{d}')
                        model.AddBoolAnd([is_off_matrix[i, d], is_off_matrix[i, d+1]]).OnlyEnforceIf(pair_consec)
                        model.AddBoolOr([is_off_matrix[i, d].Not(), is_off_matrix[i, d+1].Not()]).OnlyEnforceIf(pair_consec.Not())
                        consec_off_vars.append(pair_consec)
                model.Maximize(sum(consec_off_vars))

                # =====================================================================
                # PERBAIKAN BARU: LOGIKA KUNCI LIBUR MINGGU TRANSISI KALENDER UTUH 2-3 HARI
                # =====================================================================
                riwayat_off_bulan_lalu = {}
                for i in range(num_karyawan):
                    riwayat_off_bulan_lalu[i] = [1 if s == 0 else 0 for s in riwayat_mei_seminggu[i]]

                jumlah_hari_bulan_lalu_di_minggu_awal = hari_pertama_idx

                weeks = []
                current_week = []
                for d in range(num_hari):
                    current_week.append(d)
                    if hari_ke_nama[d] == 'Minggu' or d == num_hari - 1:
                        weeks.append(current_week)
                        current_week = []

                for idx_w, week in enumerate(weeks):
                    if idx_w == 0 and jumlah_hari_bulan_lalu_di_minggu_awal > 0:
                        # JALUR TRANSISI: Menyambung Senin-Selasa bulan lalu dengan Rabu-Minggu bulan ini
                        for i in range(num_karyawan):
                            tgl_ambil_bulan_lalu = riwayat_off_bulan_lalu[i][-jumlah_hari_bulan_lalu_di_minggu_awal:]
                            total_off_bulan_lalu = sum(tgl_ambil_bulan_lalu)
                            
                            # Kunci mati: Libur di minggu gabungan kalender ini WAJIB 2-3 hari!
                            model.Add(total_off_bulan_lalu + sum(is_off_matrix[i, d] for d in week) >= 2)
                            model.Add(total_off_bulan_lalu + sum(is_off_matrix[i, d] for d in week) <= 3)
                    elif len(week) == 7:
                        # MINGGU REGULER PENH
                        for i in range(num_karyawan):
                            model.Add(sum(is_off_matrix[i, d] for d in week) >= 2)
                            model.Add(sum(is_off_matrix[i, d] for d in week) <= 3)
                    else:
                        # MINGGU TERAKHIR POTONGAN
                        for i in range(num_karyawan):
                            model.Add(sum(is_off_matrix[i, d] for d in week) <= 2)

                # Kapasitas Shift Harian & SYARAT 3: Kunci agar Saut WAJIB BERDUA di shift manapun
                for d in range(num_hari):
                    for s in [1, 2, 3]:
                        is_in_shift = []
                        for i in range(num_karyawan):
                            in_shift = model.NewBoolVar(f's_{s}_i_{i}_d_{d}')
                            model.Add(x[i, d] == s).OnlyEnforceIf(in_shift)
                            model.Add(x[i, d] != s).OnlyEnforceIf(in_shift.Not())
                            is_in_shift.append(in_shift)
                        
                        if s == 3:
                            model.Add(sum(is_in_shift) == 2) 
                        else:
                            model.Add(sum(is_in_shift) >= 1)
                            model.Add(sum(is_in_shift) <= 2)

                        if saut_idx != -1:
                            saut_disini = model.NewBoolVar(f'saut_is_at_s_{s}_d_{d}')
                            model.Add(x[saut_idx, d] == s).OnlyEnforceIf(saut_disini)
                            model.Add(x[saut_idx, d] != s).OnlyEnforceIf(saut_disini.Not())
                            
                            if s == 2:
                                model.Add(sum(is_in_shift) == 2).OnlyEnforceIf(saut_disini)
                            elif s == 1:
                                s1_is_one = model.NewBoolVar(f's1_is_one_d_{d}')
                                model.Add(sum(is_in_shift) == 1).OnlyEnforceIf(s1_is_one)
                                model.Add(sum(is_in_shift) != 1).OnlyEnforceIf(s1_is_one.Not())
                                
                                saut_sendirian = model.NewBoolVar(f'saut_alone_s1_d_{d}')
                                model.AddBoolAnd([saut_disini, s1_is_one]).OnlyEnforceIf(saut_sendirian)
                                model.AddBoolOr([saut_disini.Not(), s1_is_one.Not()]).OnlyEnforceIf(saut_sendirian.Not())
                                
                                if hari_ke_nama[d] in ['Sabtu', 'Minggu']:
                                    model.Add(saut_sendirian == 0)
                                else:
                                    saut_alone_weekdays.append(saut_sendirian) if 'saut_alone_weekdays' in locals() else locals().update({'saut_alone_weekdays': [saut_sendirian]})

                if saut_idx != -1 and 'saut_alone_weekdays' in locals():
                    model.Add(sum(saut_alone_weekdays) <= 4)

                # Transisi Istirahat Minimal Lintas Bulan
                for i in range(num_karyawan):
                    last_mei = riwayat_mei_seminggu[i][-1]
                    if last_mei == 3:
                        model.AddAllowedAssignments([x[i, 0]], [[0], [3]])
                    elif last_mei == 2:
                        model.Add(x[i, 0] != 1)
                        
                    for d in range(num_hari - 1):
                        is_shift3 = model.NewBoolVar(f'is_s3_{i}_{d}')
                        model.Add(x[i, d] == 3).OnlyEnforceIf(is_shift3)
                        model.Add(x[i, d] != 3).OnlyEnforceIf(is_shift3.Not())
                        model.AddAllowedAssignments([x[i, d], x[i, d+1]], [[3, 0], [3, 3]]).OnlyEnforceIf(is_shift3)
                        
                        is_shift2 = model.NewBoolVar(f'is_s2_{i}_{d}')
                        model.Add(x[i, d] == 2).OnlyEnforceIf(is_shift2)
                        model.Add(x[i, d] != 2).OnlyEnforceIf(is_shift2.Not())
                        model.Add(x[i, d+1] != 1).OnlyEnforceIf(is_shift2)

                # Maksimal Kerja Berurutan 5 Hari Lintas Batas Bulan
                for i in range(num_karyawan):
                    prev_work_offs = [1 if s == 0 else 0 for s in riwayat_mei_seminggu[i][-5:]]
                    current_work_offs = [is_off_matrix[i, d] for d in range(num_hari)]
                    
                    all_work_offs = prev_work_offs + current_work_offs
                    for start_day in range(len(all_work_offs) - 5):
                        window = all_work_offs[start_day : start_day + 6]
                        model.Add(sum(window) >= 1)

                # Kunci Jatah Total Shift 1 Saut Agar Tetap Dominan (8 - 12 Hari)
                for i in range(num_karyawan):
                    emp_s1_days = []
                    for d in range(num_hari):
                        is_s1 = model.NewBoolVar(f's1_count_i_{i}_d_{d}')
                        model.Add(x[i, d] == 1).OnlyEnforceIf(is_s1)
                        model.Add(x[i, d] != 1).OnlyEnforceIf(is_s1.Not())
                        emp_s1_days.append(is_s1)
                    
                    if i == saut_idx and saut_idx != -1:
                        model.Add(sum(emp_s1_days) >= 8)  
                        model.Add(sum(emp_s1_days) <= 12) 
                    else:
                        model.Add(sum(emp_s1_days) >= 1)
                        model.Add(sum(emp_s1_days) <= 9)

                # Distribusi Adil Shift 3 (Malam)
                for i in range(num_karyawan):
                    if i != 0:
                        emp_s3_days = []
                        for d in range(num_hari):
                            is_s3 = model.NewBoolVar(f'fair_s3_i_{i}_d_{d}')
                            model.Add(x[i, d] == 3).OnlyEnforceIf(is_s3)
                            model.Add(x[i, d] != 3).OnlyEnforceIf(is_s3.Not())
                            emp_s3_days.append(is_s3)
                        
                        if i == saut_idx:
                            model.Add(sum(emp_s3_days) >= 1)
                            model.Add(sum(emp_s3_days) <= 5)
                        else:
                            model.Add(sum(emp_s3_days) >= 8)
                            model.Add(sum(emp_s3_days) <= 14)

                # Eksekusi Solver
                solver = cp_model.CpSolver()
                solver.parameters.linearization_level = 0
                solver.parameters.max_time_in_seconds = 20.0
                status = solver.Solve(model)

                if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
                    wb = openpyxl.Workbook()
                    ws = wb.active
                    ws.title = "Sheet1"
                    ws.views.sheetView[0].showGridLines = True

                    fill_s1 = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
                    font_s1 = Font(name="Calibri", size=11, color="006100", bold=True)
                    fill_s2 = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
                    font_s2 = Font(name="Calibri", size=11, color="9C6500", bold=True)
                    fill_s3 = PatternFill(start_color="B4C6E7", end_color="B4C6E7", fill_type="solid")
                    font_s3 = Font(name="Calibri", size=11, color="1F4E78", bold=True)
                    fill_off = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
                    font_off = Font(name="Calibri", size=11, color="A6A6A6")
                    font_header = Font(name="Calibri", size=11, bold=True)
                    fill_header = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
                    thin_border = Border(
                        left=Side(style='thin', color='D9D9D9'), right=Side(style='thin', color='D9D9D9'),
                        top=Side(style='thin', color='D9D9D9'), bottom=Side(style='thin', color='D9D9D9')
                    )

                    ws.cell(row=1, column=1, value=date_bulan_depan.strftime("%Y-%m-%d")).font = font_header

                    headers_kiri = ["Nama", "Layer", "Shift 1", "Shift 2", "Shift 3", "Libur", "Kerja", ""]
                    for col_idx, text in enumerate(headers_kiri, start=1):
                        cell = ws.cell(row=2, column=col_idx, value=text)
                        cell.font = font_header
                        cell.fill = fill_header

                    for col_idx, text in enumerate(["Shift 1", "Shift 2", "Shift 3", "Libur", "Kerja"], start=3):
                        ws.cell(row=3, column=col_idx, value=text).font = font_header

                    for r in [2, 3]:
                        for c in range(1, 9):
                            ws.cell(row=r, column=c).fill = fill_header
                            ws.cell(row=r, column=c).alignment = Alignment(horizontal="center" if c > 1 else "left", vertical="center")

                    col_mapping = {}
                    current_col = 9
                    for d in range(num_hari):
                        col_mapping[d] = current_col
                        ws.cell(row=2, column=current_col, value=d+1).font = font_header
                        ws.cell(row=2, column=current_col).fill = fill_header
                        ws.cell(row=2, column=current_col).alignment = Alignment(horizontal="center")
                        
                        ws.cell(row=3, column=current_col, value=hari_ke_nama[d]).font = font_header
                        ws.cell(row=3, column=current_col).fill = fill_header
                        ws.cell(row=3, column=current_col).alignment = Alignment(horizontal="center")
                        
                        if hari_ke_nama[d] == 'Minggu' and d != num_hari - 1:
                            current_col += 1
                            ws.cell(row=2, column=current_col).fill = fill_header
                            ws.cell(row=3, column=current_col).fill = fill_header
                        current_col += 1

                    for i in range(num_karyawan):
                        row_idx = i + 4
                        s1_c = sum(solver.Value(x[i, d]) == 1 for d in range(num_hari))
                        s2_c = sum(solver.Value(x[i, d]) == 2 for d in range(num_hari))
                        s3_c = sum(solver.Value(x[i, d]) == 3 for d in range(num_hari))
                        off_c = sum(solver.Value(x[i, d]) == 0 for d in range(num_hari))
                        kerja_c = s1_c + s2_c + s3_c
                        
                        ws.cell(row=row_idx, column=1, value=karyawan[i]).font = Font(name="Calibri", size=11)
                        ws.cell(row=row_idx, column=2, value="" if i == 0 else "L1").alignment = Alignment(horizontal="center")
                        ws.cell(row=row_idx, column=3, value=s1_c).alignment = Alignment(horizontal="center")
                        ws.cell(row=row_idx, column=4, value=s2_c).alignment = Alignment(horizontal="center")
                        ws.cell(row=row_idx, column=5, value=s3_c).alignment = Alignment(horizontal="center")
                        ws.cell(row=row_idx, column=6, value=off_c).alignment = Alignment(horizontal="center")
                        ws.cell(row=row_idx, column=7, value=kerja_c).alignment = Alignment(horizontal="center")
                        
                        for c in range(1, 9): ws.cell(row=row_idx, column=c).border = thin_border
                            
                        for d in range(num_hari):
                            target_col = col_mapping[d]
                            val = solver.Value(x[i, d])
                            cell = ws.cell(row=row_idx, column=target_col)
                            cell.border = thin_border
                            cell.alignment = Alignment(horizontal="center", vertical="center")
                            
                            if val == 1:
                                cell.value = 1; cell.fill = fill_s1; cell.font = font_s1
                            elif val == 2:
                                cell.value = 2; cell.fill = fill_s2; cell.font = font_s2
                            elif val == 3:
                                cell.value = 3; cell.fill = fill_s3; cell.font = font_s3
                            else:
                                cell.value = "OFF"; cell.fill = fill_off; cell.font = font_off

                    for col in ws.columns:
                        max_len = max(len(str(cell.value or '')) for cell in col)
                        col_letter = get_column_letter(col[0].column)
                        ws.column_dimensions[col_letter].width = max(max_len + 3, 6)
                    ws.column_dimensions['A'].width = 38

                    excel_buffer = io.BytesIO()
                    wb.save(excel_buffer)
                    excel_buffer.seek(0)
                    
                    st.success("🎉 Penjadwalan sukses dibentuk tanpa ada aturan yang melanggar!")
                    st.download_button(
                        label="📥 Download Berkas Excel Jadwal Baru",
                        data=excel_buffer,
                        file_name=f"Jadwal_Otomatis_{date_bulan_depan.strftime('%B_%Y')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.error("Gagal! Algoritma mendeteksi adanya bentrokan aturan mutlak. Mohon periksa kembali kesesuaian jatah libur tim.")
    except Exception as e:
        st.error(f"Terjadi kesalahan format pembacaan file: {e}. Pastikan file template sesuai dengan format aslinya.")
