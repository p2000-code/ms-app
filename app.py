# --- פונקציה להדגשת מילת החיפוש ---
def highlight_term(text, term):
    if not term:
        return text
    import re
    # הדגשה בצבע חום-זהב עמוק שמתאים לעיצוב התורני
    highlighted = re.sub(f"({re.escape(term)})", r'<span style="color: #b8860b; font-weight: bold; border-bottom: 1px solid #b8860b;">\1</span>', text, flags=re.IGNORECASE)
    return highlighted

# --- ממשק החיפוש המשודרג ---
st.markdown('<p style="text-align: right; font-weight: bold;">חיפוש מהיר בקטלוג:</p>', unsafe_allow_html=True)
search_term = st.text_input("הזן מילת חיפוש:", placeholder="למשל: פאריטש, אדמו''ר הזקן...", label_visibility="collapsed")

selected_ms_id_from_search = ""

if df_catalog is not None and (search_term or selected_shelf != "הכל"):
    filtered_df = df_catalog.copy()
    if selected_shelf != "הכל":
        filtered_df = filtered_df[filtered_df['shelf'] == selected_shelf]
    
    if search_term:
        filtered_df = filtered_df[filtered_df['desc'].str.contains(search_term, na=False, case=False)]
    
    if not filtered_df.empty:
        st.markdown(f'<p style="text-align: right; font-size: 13px; color: #666;">נמצאו {len(filtered_df)} תוצאות (מציג את הראשונות):</p>', unsafe_allow_html=True)
        
        # הצגת התוצאות ככרטיסיות
        for i, row in filtered_df.head(10).iterrows():
            with st.container():
                # יצירת מבנה של כרטיס עם מסגרת עדינה
                desc_highlighted = highlight_term(row['desc'], search_term)
                
                # תצוגת המידע - כאן הטקסט יכול לגלוש לשורות נוספות
                st.markdown(f"""
                <div style="background-color: #fcfaf5; padding: 15px; border-radius: 5px; border-right: 4px solid #1e3d59; margin-bottom: 10px; box-shadow: 1px 1px 3px rgba(0,0,0,0.05);">
                    <div style="font-weight: bold; color: #1e3d59; font-size: 16px;">מספר כתב יד: {row['ms_id']}</div>
                    <div style="font-size: 14px; color: #444; margin: 5px 0;">מדור: {row['shelf']} | דפים: {row['pages']}</div>
                    <div style="font-size: 15px; line-height: 1.4; color: #000;">{desc_highlighted}</div>
                </div>
                """, unsafe_allow_html=True)
                
                # כפתור בחירה לכל תוצאה
                if st.button(f"בחר כתב יד {row['ms_id']}", key=f"btn_{row['ms_id']}"):
                    selected_ms_id_from_search = row['ms_id']
                    st.rerun() # מרענן את הדף כדי לעדכן את שדה ה-ID למטה
    else:
        st.warning("לא נמצאו תוצאות מתאימות.")
