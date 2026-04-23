import os
import time
import logging
import requests
import concurrent.futures
import streamlit as st
import gc
import base64
import json
import pandas as pd
import shutil  # נוסף עבור פתרון התיקייה הסטטית
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from pypdf import PdfWriter
from weasyprint import HTML

# 1. הגדרות תצוגה
st.set_page_config(page_title="הורדת כתבי יד - ספריית חבדי", layout="centered")

# --- אתחול משתני זיכרון (Session State) ---
if "pdf_data" not in st.session_state:
    st.session_state.pdf_data = None
    st.session_state.pdf_filename = None  # נוסף עבור הקישור הישיר
    st.session_state.ms_id = None
    st.session_state.duration = None

# 2. עיצוב ממשק יציב ונקי (CSS)
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

        .stMarkdown, .stText, .stInfo, .stError, .stWarning, .stCheckbox {
            direction: rtl;
            text-align: right;
        }

        /* עיצוב כפתור הורדה סולידי */
        div.stButton > button:first-child {
            background-color: #1e3d59;
            color: #ffffff !important;
            width: 100%;
            border-radius: 4px;
            height: 3.5em;
            font-weight: bold;
            border: none;
            margin-top: 15px;
        }

        /* עיצוב תיבת הפרטים המלאה */
        .details-box {
            background-color: #ffffff;
            padding: 20px;
            border: 1px solid #dcd6c3;
            border-radius: 8px;
            margin-top: 10px;
            margin-bottom: 20px;
            line-height: 1.6;
            color: #000;
        }

        /* הנחיית משתמש ברורה */
        .input-instruction {
            font-size: 15px;
            color: #444;
            margin-bottom: 8px;
            text-align: right;
            font-weight: bold;
        }
        
        /* תיקון ריווח שדות */
        .stTextInput {
            margin-bottom: 20px;
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
        except Exception as e:
            return None
    return None

df_catalog = load_catalog()

def get_manuscript_metadata(ms_id):
    url = f"https://chabadlibrary.org/catalog/index1.php?frame=main&catalog=mscatalog&mode=details&volno={ms_id}&limit=0&search_mode=simple"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    metadata = {
        "מספר כתב יד": str(ms_id), 
        "מדור ומדף": "", 
        "תיאור": [],
        "base_url": f"https://s3.wasabisys.com/chabadlibrary/ms/{ms_id}/{ms_id}_page_",
        "expected_pages": 0
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8' # תוקן ל-UTF-8 כדי למנוע ג'יבריש
        soup = BeautifulSoup(response.text, 'html.parser')
        
        lines = soup.get_text(separator='\n', strip=True).split('\n')
        for line in lines:
            line = line.strip()
            if not line or "קטלוג ספריית" in line or "לתצלום הספר" in line or "chabadlibrary.org" in line:
                continue
            if "מדור ומדף:" in line:
                metadata["מדור ומדף"] = line.split("מדור ומדף:")[1].strip()
                continue
            metadata["תיאור"].append(line)
            
        config_link = next((a['href'] for a in soup.find_all('a', href=True) if "config=" in a['href']), None)
        if config_link:
            encoded_str = config_link.split("config=")[1]
            missing_padding = len(encoded_str) % 4
            if missing_padding: encoded_str += '=' * (4 - missing_padding)
            data = json.loads(base64.b64decode(encoded_str))
            
            hb_id = data.get('row', {}).get('hb_id', '')
            pages = data.get('row', {}).get('pages', 0)
            
            if hb_id:
                metadata["base_url"] = f"https://s3.wasabisys.com/chabadlibrary/ms/{hb_id}/{hb_id}_page_"
                metadata["expected_pages"] = int(pages)
                
    except Exception as e:
        pass

    if not metadata["מדור ומדף"]: metadata["מדור ומדף"] = "לא נמצא"
    if not metadata["תיאור"]: metadata["תיאור"] = ["לא ניתן היה לשלוף תיאור מלא"]
    
    return metadata

def create_cover_page_html(metadata, output_filename, range_text=""):
    desc_html = "".join([f"<p>{line}</p>" for line in metadata['תיאור']])
    range_html = f"<h3>{range_text}</h3>" if range_text else ""
    
    html_content = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="he">
    <head>
        <meta charset="utf-8">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@400;700&display=swap');
            body {{ font-family: 'Frank Ruhl Libre', serif; text-align: center; padding-top: 100px; color: #000; }}
            h1 {{ font-size: 50px; margin-bottom: 20px; }}
            h2 {{ font-size: 30px; margin-bottom: 20px; font-weight: normal; }}
            h3 {{ font-size: 24px; margin-bottom: 50px; font-weight: normal; }}
            .description {{ font-size: 22px; line-height: 1.6; max-width: 80%; margin: 0 auto; text-align: right; }}
            p {{ margin: 8px 0; }}
        </style>
    </head>
    <body>
        <h1>כתב יד מספר {metadata['מספר כתב יד']}</h1>
        <h2>מדור ומדף: {metadata['מדור ומדף']}</h2>
        {range_html}
        <div class="description">{desc_html}</div>
    </body>
    </html>
    """
    HTML(string=html_content).write_pdf(output_filename)

def download_single_page(page_num, base_url, max_retries=3):
    url = f"{base_url}{page_num}.pdf"
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                return page_num, response.content, 200
            elif response.status_code == 404:
                return page_num, None, 404
            time.sleep(1)
        except:
            time.sleep(1)
    return page_num, None, 500

def log_to_google_form(ms_id, pages_range, processing_time):
    url = "https://docs.google.com/forms/d/e/1FAIpQLSenYAwJHVW5jV-hU6hKF5b16LU6ku-v6Pqz6vCq2LFjSe40qA/formResponse"
    form_data = {
        "entry.475870562": str(ms_id),         
        "entry.148108717": str(pages_range),   
        "entry.1430710188": f"{processing_time} שניות"
    }
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        requests.post(url, data=form_data, headers=headers, timeout=5)
    except:
        pass

# --- ממשק המשתמש הראשי ---

st.markdown('<p class="input-instruction">להצגת פרטי כתב היד, יש להקיש אנטר (Enter) לאחר הזנת המספר:</p>', unsafe_allow_html=True)
ms_id_input = st.text_input(
    "מספר כתב יד",
    placeholder="למשל: 1102 או 3284",
    label_visibility="collapsed"
)

if ms_id_input and df_catalog is not None:
    ms_id_clean = ms_id_input.strip()
    row = df_catalog[df_catalog['ms_id'] == ms_id_clean]
    
    if not row.empty:
        st.markdown(f"""
        <div class="details-box">
            <div style="font-weight: bold; color: #1e3d59; font-size: 18px; border-bottom: 1px solid #dcd6c3; padding-bottom: 5px; margin-bottom: 10px;">
                פרטי כתב יד {ms_id_clean}
            </div>
            <div style="font-size: 15px;">
                <strong>מדור ומדף:</strong> {row['shelf'].values[0]}<br>
                <strong>מספר עמודים (מתוך ה-CSV):</strong> {row['pages'].values[0]}<br><br>
                <strong>תיאור מלא:</strong><br>
                {row['desc'].values[0]}
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.warning("מספר כתב היד לא נמצא בקטלוג המקומי.")

specific_range = st.checkbox("הורדת טווח עמודים ספציפי")
start_page, end_page = 1, 10
if specific_range:
    c1, c2 = st.columns(2)
    with c1: start_page = st.number_input("מעמוד", min_value=1, value=1)
    with c2: end_page = st.number_input("עד עמוד", min_value=1, value=10)

if st.button("הורד עכשיו"):
    if not ms_id_input:
        st.warning("אנא הכנס מספר כתב יד.")
    else:
        # איפוס נתוני הזיכרון
        st.session_state.pdf_data = None
        st.session_state.pdf_filename = None
        
        ms_id = ms_id_input.strip()
        start_time = time.time()
        
        with st.spinner('מעבד את הבקשה ומזהה חיבור חכם...'):
            meta = get_manuscript_metadata(ms_id)
            range_txt = f"עמודים {start_page} עד {end_page}" if specific_range else ""
            cover_file = f"cover_{ms_id}.pdf"
            create_cover_page_html(meta, cover_file, range_txt)
            
            base_url = meta["base_url"]
            chunk_files = [cover_file]
            
            curr = start_page if specific_range else 1
            last = end_page if specific_range else 3000
            
            keep_going = True
            consecutive_404_count = 0 
            
            status = st.empty()
            progress = st.progress(0)
            
            while keep_going and curr <= last:
                batch_size = 20
                limit = min(curr + batch_size - 1, last)
                status.info(f"מוריד וסורק דפים {curr} עד {limit}...")
                
                results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
                    futures = {executor.submit(download_single_page, p, base_url): p for p in range(curr, limit + 1)}
                    for f in concurrent.futures.as_completed(futures):
                        results.append(f.result())
                
                results.sort(key=lambda x: x[0])
                chunk_merger = PdfWriter()
                temp_list = []
                
                for p_num, content, code in results:
                    if content is None or code == 404:
                        consecutive_404_count += 1
                        if consecutive_404_count >= 3:
                            keep_going = False
                            break
                    else:
                        consecutive_404_count = 0
                        temp_name = f"temp_{ms_id}_{p_num}.pdf"
                        with open(temp_name, 'wb') as f:
                            f.write(content)
                        chunk_merger.append(temp_name)
                        temp_list.append(temp_name)
                
                if temp_list:
                    chunk_name = f"chunk_{ms_id}_{curr}.pdf"
                    chunk_merger.write(chunk_name)
                    chunk_files.append(chunk_name)
                
                chunk_merger.close()
                for f in temp_list:
                    if os.path.exists(f): os.remove(f)
                
                curr = limit + 1
                progress.progress(min(curr / 2000, 1.0))

            final_file = f"Manuscript_{ms_id}.pdf"
            final_merger = PdfWriter()
            for f in chunk_files:
                final_merger.append(f)
            final_merger.write(final_file)
            final_merger.close()
            
            # --- שלב פתרון התיקייה הסטטית ---
            os.makedirs("static", exist_ok=True)
            
            # ניקוי קבצים ישנים (בני יותר מ-15 דקות)
            now = time.time()
            for f in os.listdir("static"):
                f_path = os.path.join("static", f)
                if os.path.isfile(f_path) and os.path.getmtime(f_path) < now - 900:
                    os.remove(f_path)

            # העתקת הקובץ לתיקייה הציבורית
            static_filename = f"Manuscript_{ms_id}.pdf"
            static_path = os.path.join("static", static_filename)
            shutil.copy(final_file, static_path)

            # שמירה לזיכרון ה-session
            with open(final_file, "rb") as f:
                st.session_state.pdf_data = f.read()
            st.session_state.pdf_filename = static_filename
            st.session_state.ms_id = ms_id
            st.session_state.duration = round(time.time() - start_time, 1)
            
            # ניקוי קבצי עבודה מהשרת
            for f in chunk_files:
                if os.path.exists(f): os.remove(f)
            if os.path.exists(final_file): os.remove(final_file)
            
            status.empty()
            progress.empty()
            
            pages_downloaded = f"{start_page}-{end_page}" if specific_range else "הורדה מלאה"
            log_to_google_form(ms_id, pages_downloaded, st.session_state.duration)
            gc.collect()

# --- הצגת הכפתורים (שורדים רענון) ---
if st.session_state.pdf_data is not None:
    st.success(f"הקובץ מוכן! (זמן תהליך: {st.session_state.duration} שניות)")
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="שמור במחשב", 
            data=st.session_state.pdf_data, 
            file_name=f"Manuscript_{st.session_state.ms_id}.pdf", 
            mime="application/pdf", 
            use_container_width=True
        )
    with col2:
        # הקישור הישיר לתיקייה הסטטית (ללא Base64)
        file_url = f"app/static/{st.session_state.pdf_filename}"
        html_link = f"""
        <a href="{file_url}" target="_blank" 
           style="display: flex; align-items: center; justify-content: center; 
                  padding: 10px 20px; color: white; background-color: #2b2b36; 
                  border: 1px solid #4a4a5a; border-radius: 5px; text-decoration: none; 
                  font-size: 16px; font-weight: bold; width: 100%; height: 45px; box-sizing: border-box;">
            צפה בכתב היד
        </a>
        """
        st.markdown(html_link, unsafe_allow_html=True)
