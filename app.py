import os
import time
import logging
import requests
import concurrent.futures
import streamlit as st
import gc
import base64
import re
import pandas as pd
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from pypdf import PdfWriter
from weasyprint import HTML

# 1. הגדרות תצוגה
st.set_page_config(page_title="הורדת כתבי יד - ספריית חבדי", layout="centered")

# 2. עיצוב ממשק (CSS) - סגנון פרגמנט תורני
st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@400;700&display=swap');

        .stApp {
            background-color: #fdf6e3;
            font-family: 'Frank Ruhl Libre', serif;
            direction: rtl;
        }

        .subtle-header {
            text-align: center;
            padding-bottom: 10px;
            border-bottom: 1px solid #dcd6c3;
            margin-bottom: 35px;
            color: #1e3d59;
        }

        .stMarkdown, .stText, .stInfo, .stError, .stWarning, .stCheckbox, .stSidebar {
            direction: rtl;
            text-align: right;
        }

        div.stButton > button:first-child {
            background-color: #1e3d59;
            color: #ffffff !important;
            width: 100%;
            border-radius: 4px;
            height: 3.5em;
            font-weight: bold;
            border: none;
            margin-top: 10px;
        }
        
        section[data-testid="stSidebar"] {
            background-color: #f5eee0;
            border-left: 1px solid #dcd6c3;
        }
        
        .result-card {
            background-color: #fcfaf5; 
            padding: 15px; 
            border-radius: 5px; 
            border-right: 4px solid #1e3d59; 
            margin-bottom: 10px; 
            box-shadow: 1px 1px 3px rgba(0,0,0,0.05);
        }

        .input-instruction {
            font-size: 15px;
            color: #444;
            margin-bottom: 8px;
            text-align: right;
            font-weight: bold;
        }
    </style>
    
    <div class="subtle-header">
        <h1>הורדת כתבי יד - ספריית חב"ד</h1>
    </div>
""", unsafe_allow_html=True)

logging.getLogger('fontTools').setLevel(logging.WARNING)
logging.getLogger('weasyprint').setLevel(logging.WARNING)

# --- פונקציות עזר ---

@st.cache_data
def load_catalog():
    file_name = 'catalog.csv'
    if os.path.exists(file_name):
        try:
            df = pd.read_csv(file_name, header=None, skiprows=1, encoding='utf-8')
            df = df[[0, 1, 2, 17]]
            df.columns = ['ms_id', 'shelf', 'desc', 'pages']
            df['ms_id'] = df['ms_id'].astype(str).str.strip()
            df['shelf'] = df['shelf'].fillna("ללא מדור").astype(str).str.strip()
            df['shelf'] = df['shelf'].replace('[לד', 'לד')
            df['desc'] = df['desc'].fillna("").astype(str)
            return df
        except:
            return None
    return None

def highlight_term(text, term):
    if not term:
        return text
    highlighted = re.sub(f"({re.escape(term)})", r'<span style="color: #b8860b; font-weight: bold; border-bottom: 1px solid #b8860b;">\1</span>', text, flags=re.IGNORECASE)
    return highlighted

def get_manuscript_metadata(ms_id):
    url = f"https://chabadlibrary.org/catalog/index1.php?frame=main&catalog=mscatalog&mode=details&volno={ms_id}&limit=0&search_mode=simple"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        metadata = {"מספר כתב יד": str(ms_id), "מדור ומדף": "", "תיאור": []}
        lines = soup.get_text(separator='\n', strip=True).split('\n')
        for line in lines:
            line = line.strip()
            if not line or "קטלוג ספריית" in line or "chabadlibrary.org" in line: continue
            if "מדור ומדף:" in line:
                metadata["מדור ומדף"] = line.split("מדור ומדף:")[1].strip()
                continue
            metadata["תיאור"].append(line)
        return metadata
    except:
        return {"מספר כתב יד": str(ms_id), "מדור ומדף": "לא נמצא", "תיאור": ["לא ניתן היה לשלוף תיאור מלא"]}

def create_cover_page_html(metadata, output_filename, range_text=""):
    desc_html = "".join([f"<p>{line}</p>" for line in metadata['תיאור']])
    html_content = f"""
    <html dir="rtl"><body style="font-family: serif; text-align: center; padding-top: 100px;">
        <h1>כתב יד מספר {metadata['מספר כתב יד']}</h1>
        <h2>מדור ומדף: {metadata['מדור ומדף']}</h2>
        <h3>{range_text}</h3>
        <div style="font-size: 20px; max-width: 80%; margin: 0 auto; text-align: right; border-right: 3px solid #b8860b; padding-right: 15px;">{desc_html}</div>
    </body></html>
    """
    HTML(string=html_content).write_pdf(output_filename)

def download_single_page(page_num, base_url):
    url = f"{base_url}{page_num}.pdf"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200: return page_num, response.content, 200
        return page_num, None, response.status_code
    except: return page_num, None, 500

def open_pdf_in_new_tab(file_path, ms_id):
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    html_code = f"""
    <button onclick="var win = window.open('', '_blank'); win.document.write('<iframe src=\\'data:application/pdf;base64,{base64_pdf}\\' frameborder=\\'0\\' style=\\'width:100%; height:100%; position:absolute;\\'></iframe>');" 
    style="cursor: pointer; padding: 10px; color: white; background-color: #2b2b36; border-radius: 5px; width: 100%; font-weight: bold;">צפה בכתב היד</button>
    """
    components.html(html_code, height=60)

# --- לוגיקה ראשית ---

df_catalog = load_catalog()

# איתחול Session State
if 'selected_ms_id' not in st.session_state: st.session_state['selected_ms_id'] = ""
if 'page_number' not in st.session_state: st.session_state['page_number'] = 0

# 1. Sidebar - סינון מדור
selected_shelf = "הכל"
if df_catalog is not None:
    st.sidebar.header("סינון")
    to_remove = ['*', '#', '2', '3', 'לא', '8', "אבולעפיא, חי רפאל ידידי'"]
    all_shelves = df_catalog['shelf'].unique().tolist()
    clean_shelves = [s for s in all_shelves if s not in to_remove]
    selected_shelf = st.sidebar.selectbox("בחר או הקלד שם מדור:", ["הכל"] + sorted(clean_shelves))

# 2. חיפוש טקסטואלי ודפדוף
st.markdown('<p style="text-align: right; font-weight: bold;">חיפוש מהיר בקטלוג:</p>', unsafe_allow_html=True)
search_term = st.text_input("הזן מילת חיפוש:", placeholder="למשל: פאריטש...", label_visibility="collapsed")

if df_catalog is not None and (search_term or selected_shelf != "הכל"):
    f_df = df_catalog.copy()
    if selected_shelf != "הכל": f_df = f_df[f_df['shelf'] == selected_shelf]
    if search_term: f_df = f_df[f_df['desc'].str.contains(search_term, na=False, case=False)]
    
    total_results = len(f_df)
    if total_results > 0:
        results_per_page = 20
        total_pages = (total_results // results_per_page) + (1 if total_results % results_per_page > 0 else 0)
        
        if st.session_state['page_number'] >= total_pages: st.session_state['page_number'] = 0

        st.markdown(f'<p style="text-align: right; font-size: 13px; color: #666;">נמצאו {total_results} תוצאות (עמוד {st.session_state["page_number"] + 1} מתוך {total_pages}):</p>', unsafe_allow_html=True)
        
        start_idx = st.session_state['page_number'] * results_per_page
        current_page_df = f_df.iloc[start_idx : start_idx + results_per_page]
        
        for i, row in current_page_df.iterrows():
            desc_h = highlight_term(row['desc'], search_term)
            st.markdown(f"""
            <div class="result-card">
                <div style="font-weight: bold; color: #1e3d59;">כתב יד: {row['ms_id']}</div>
                <div style="font-size: 13px; color: #666;">מדור: {row['shelf']} | דפים: {row['pages']}</div>
                <div style="font-size: 15px; margin-top: 5px;">{desc_h}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"בחר {row['ms_id']}", key=f"btn_{row['ms_id']}"):
                st.session_state['selected_ms_id'] = row['ms_id']
                st.rerun()

        # כפתורי ניווט
        col_prev, col_page, col_next = st.columns([1, 2, 1])
        with col_next:
            if st.session_state['page_number'] > 0:
                if st.button("<< הקודם"):
                    st.session_state['page_number'] -= 1
                    st.rerun()
        with col_page:
            st.markdown(f"<p style='text-align:center;'>עמוד {st.session_state['page_number'] + 1}</p>", unsafe_allow_html=True)
        with col_prev:
            if st.session_state['page_number'] < total_pages - 1:
                if st.button("הבא >>"):
                    st.session_state['page_number'] += 1
                    st.rerun()
    elif search_term:
        st.warning("לא נמצאו תוצאות.")

st.divider()

# 3. הזנת ID סופית והורדה
st.markdown('<p class="input-instruction">להצגת פרטי כתב היד, יש להקיש אנטר (Enter) לאחר הזנת המספר:</p>', unsafe_allow_html=True)
ms_id_final = st.text_input("ID", value=st.session_state['selected_ms_id'], label_visibility="collapsed")

if ms_id_final and df_catalog is not None:
    ms_clean = ms_id_final.strip()
    row = df_catalog[df_catalog['ms_id'] == ms_clean]
    if not row.empty:
        st.info(f"נבחר: {row['desc'].values[0][:200]}...")
    
    specific_range = st.checkbox("הורדת טווח עמודים ספציפי")
    start_p, end_p = 1, 10
    if specific_range:
        c1, c2 = st.columns(2)
        with c1: start_p = st.number_input("מעמוד", min_value=1, value=1)
        with c2: end_p = st.number_input("עד עמוד", min_value=1, value=10)

    if st.button("הורד עכשיו"):
        with st.spinner('מעבד את הבקשה...'):
            ms_id = ms_clean
            meta = get_manuscript_metadata(ms_id)
            cover = f"cover_{ms_id}.pdf"
            create_cover_page_html(meta, cover, f"עמודים {start_p}-{end_p}" if specific_range else "")
            
            base_url = f"https://s3.wasabisys.com/chabadlibrary/ms/{ms_id}/{ms_id}_page_"
            chunk_files = [cover]
            curr, last = (start_p, end_p) if specific_range else (1, 2000)
            
            p_bar = st.progress(0)
            status = st.empty()
            
            keep_going = True
            while keep_going and curr <= last:
                batch = 20
                limit = min(curr + batch - 1, last)
                status.info(f"מוריד דפים {curr} עד {limit}...")
                
                res = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=batch) as ex:
                    futures = {ex.submit(download_single_page, p, base_url): p for p in range(curr, limit + 1)}
                    for f in concurrent.futures.as_completed(futures): res.append(f.result())
                
                res.sort(key=lambda x: x[0])
                merger = PdfWriter()
                temps = []
                for p_n, content, code in res:
                    if content is None:
                        keep_going = False
                        break
                    t_name = f"t_{ms_id}_{p_n}.pdf"
                    with open(t_name, 'wb') as f: f.write(content)
                    merger.append(t_name)
                    temps.append(t_name)
                
                if temps:
                    c_name = f"c_{ms_id}_{curr}.pdf"
                    merger.write(c_name)
                    chunk_files.append(c_name)
                merger.close()
                for f in temps: os.remove(f)
                curr = limit + 1
            
            final = f"Manuscript_{ms_id}.pdf"
            final_merger = PdfWriter()
            for f in chunk_files: final_merger.append(f)
            final_merger.write(final)
            final_merger.close()
            for f in chunk_files: os.remove(f)
            
            status.empty()
            p_bar.empty()
            st.success("הקובץ מוכן להורדה")
            col_a, col_b = st.columns(2)
            with col_a:
                with open(final, "rb") as f: st.download_button("שמור במחשב", f, file_name=final, use_container_width=True)
            with col_b: open_pdf_in_new_tab(final, ms_id)
            os.remove(final)
            gc.collect()
