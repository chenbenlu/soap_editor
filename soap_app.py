import streamlit as st
import re
import copy
from collections import defaultdict

# =========================
#  基礎資料結構與解析邏輯
# =========================
class LogEntry:
    def __init__(self, timestamp, raw_line):
        self.timestamp = timestamp
        self.raw_line = raw_line
        self.name = ""
        self.details = ""
        self.action = "Active"
        self.notes = []
        self.is_med = False

def parse_logs_from_lines(lines):
    entries = []
    current_time = None
    last_entry = None
    time_pattern = re.compile(r'列印時間:(\d{4}/\d{2}/\d{2} \d{2}:\d{2})')
    action_codes = ['NEW', 'DC', 'DC-D', 'DC-C', 'DC-E', 'CHG', 'EXTN']

    for raw in lines:
        raw = raw.rstrip('\n')
        stripped = raw.strip()
        if time_pattern.search(raw):
            current_time = time_pattern.search(raw).group(1)
            continue
        if not stripped or "類別" in raw or "醫師:" in raw: continue
        parts = stripped.split()
        if parts and parts[0] in action_codes:
            action = parts[0]
            content = stripped[len(action):].strip()
            entry = LogEntry(current_time, raw)
            entry.action = action
            entry.name = content
            entry.details = content
            entries.append(entry)
            last_entry = entry
            continue
        if stripped.startswith('(') or stripped.startswith('..'):
            if last_entry: last_entry.notes.append(stripped)
            continue
        if last_entry and raw.startswith(' '):
            if not re.search(r'\*:EMR|BLOOD GAS|EKG|Consult', stripped, re.I):
                if not re.search(r'\b(B|U|S|BV)\b', stripped):
                    last_entry.details += " " + stripped
                    last_entry.name += " " + stripped
                    continue
        entry = LogEntry(current_time, raw)
        entry.name = stripped
        entry.details = stripped
        entries.append(entry)
        last_entry = entry
    return entries

def classify_entry(entry):
    text = entry.details + " " + " ".join(entry.notes)
    if entry.name.startswith('.'):
        entry.is_med = False
        return entry
    specimen_pattern = r'\b(B|U|S|BV)\b|\b(B|U|S|BV)\s*\*:EMR'
    if re.search(specimen_pattern, text):
        entry.is_med = False
        return entry
    med_features = [
        r'\bQ\d+[HM]\b', r'\bQD\b', r'\bBID\b', r'\bTID\b', r'\bQID\b',
        r'\bONCE\b', r'\bPRN\b', r'\bIV\b', r'\bIVF\b', r'\bPO\b', r'\bTOPI\b',
        r'\d+(mg|g|gm|ml|mL|mcg|vial|tab|amp|cap|iu)\b'
    ]
    for pattern in med_features:
        if re.search(pattern, text, re.IGNORECASE):
            entry.is_med = True
            return entry
    entry.is_med = False
    return entry

def normalize_drug_name(name):
    name = re.split(r'\s{2,}', name)[0]
    name = re.sub(r'\(管\d+\)', '', name)
    dose_pattern = r'\b\d+(\.\d+)?\s*(mg|g|gm|mL|ml|mcg|mEq|vial|tab|amp|cap|iu)(/[A-Za-z]+)*\b'
    name = re.sub(dose_pattern, '', name, flags=re.IGNORECASE)
    name = re.sub(r',\s*(?=\s|$)', '', name)
    return re.sub(r'\s+', ' ', name).strip().title()

def process_logs(entries):
    med_map = defaultdict(list)
    other_map = {}
    for entry in entries:
        if entry.is_med:
            key = normalize_drug_name(entry.name)
            med_map[key].append(entry)
        else:
            clean_other = re.split(r'\s{2,}', entry.name)[0].strip()
            if clean_other and clean_other != '.' and len(clean_other) > 2:
                clean_title = clean_other.title()
                other_map[clean_title] = (clean_title, entry)
    
    final_meds = []
    for drug, history in med_map.items():
        history.sort(key=lambda x: x.timestamp)
        last = history[-1]
        status = "Discontinued" if last.action.startswith("DC") else "Active"
        display_str = f"[{'Add' if status == 'Active' else 'DC'}] {drug}"
        final_meds.append({"name": drug, "status": status, "display": display_str, "details": last.details})
    final_meds.sort(key=lambda x: (x["status"] != "Active", x["name"]))
    
    final_others = []
    for val in other_map.values():
        clean_name = val[0]
        entry_obj = val[1]
        final_others.append({"name": clean_name, "display": clean_name, "details": entry_obj.details})
    final_others.sort(key=lambda x: x["name"])
    
    return final_meds, final_others

def parse_historical_soap(soap_text):
    a_match = re.search(r'(?:^|\n)\s*A\s*:(.*?)(?=(?:^|\n)\s*P\s*:|\Z)', soap_text, re.DOTALL | re.IGNORECASE)
    p_match = re.search(r'(?:^|\n)\s*P\s*:(.*?)\Z', soap_text, re.DOTALL | re.IGNORECASE)
    
    a_text = a_match.group(1).strip() if a_match else ""
    p_text = p_match.group(1).strip() if p_match else ""
    
    problems = []
    if a_text:
        raw_items = re.split(r'\n(?=\d+\.\s)', '\n' + a_text)
        for item in raw_items:
            item = item.strip()
            if item:
                title_line = item.split('\n')[0].strip()
                problems.append({'title': title_line, 'full_content': item})
    return problems, p_text

# =========================
#  智慧合併引擎 (Smart Merge) - 置底插入
# =========================
def parse_and_merge_updates(base_text, edited_updates):
    if not edited_updates.strip():
        return base_text
    
    sections = {"[Exam]": [], "[Past treatment]": [], "[Current Management]": [], "[Consult]": []}
    current_sec = None
    
    for line in edited_updates.split('\n'):
        stripped = line.strip()
        if stripped in sections:
            current_sec = stripped
        elif current_sec and stripped:
            sections[current_sec].append(line)
            
    result_text = base_text
    for sec, lines in sections.items():
        if lines:
            block = "\n".join(lines)
            pattern_start = r'\[\s*' + re.escape(sec.strip('[]')) + r'\s*\]'
            match_start = re.search(pattern_start, result_text, re.IGNORECASE)
            
            if match_start:
                start_pos = match_start.end()
                match_next = re.search(r'\n\s*\[', result_text[start_pos:])
                if match_next:
                    insert_pos = start_pos + match_next.start()
                    result_text = result_text[:insert_pos].rstrip() + "\n" + block + "\n\n" + result_text[insert_pos:].lstrip()
                else:
                    result_text = result_text.rstrip() + "\n" + block + "\n"
            else:
                result_text = result_text.rstrip() + f"\n\n{sec}\n{block}\n"
                
    return result_text

# =========================
#  狀態管理與 Callbacks (支援刪除時光倒流)
# =========================
if 'step' not in st.session_state:
    st.session_state.step = 1
    st.session_state.original_hist_probs = []
    st.session_state.hist_probs = []
    st.session_state.hist_plan = "" 
    st.session_state.unassigned_meds = []
    st.session_state.unassigned_others = []
    st.session_state.staged = {"[Exam]": [], "[Past treatment]": [], "[Current Management]": [], "[Consult]": []}
    st.session_state.commits = [] 
    st.session_state.commit_counter = 1
    st.session_state.final_text = ""

def reset_app():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

def stage_item(item_type, data_obj, category):
    if item_type == 'med': st.session_state.unassigned_meds.remove(data_obj)
    else: st.session_state.unassigned_others.remove(data_obj)
    st.session_state.staged[category].append({'type': item_type, 'data': data_obj})

def unstage_item(category, staged_obj):
    st.session_state.staged[category].remove(staged_obj)
    if staged_obj['type'] == 'med':
        st.session_state.unassigned_meds.append(staged_obj['data'])
        st.session_state.unassigned_meds.sort(key=lambda x: (x["status"] != "Active", x["name"]))
    else:
        st.session_state.unassigned_others.append(staged_obj['data'])
        st.session_state.unassigned_others.sort(key=lambda x: x["name"])

def delete_commit(commit_id):
    commit_to_delete = next((c for c in st.session_state.commits if c['id'] == commit_id), None)
    if not commit_to_delete: return
    
    for cat, items in commit_to_delete['used_items'].items():
        for item in items:
            if item['type'] == 'med':
                if item['data'] not in st.session_state.unassigned_meds:
                    st.session_state.unassigned_meds.append(item['data'])
            else:
                if item['data'] not in st.session_state.unassigned_others:
                    st.session_state.unassigned_others.append(item['data'])
    
    st.session_state.unassigned_meds.sort(key=lambda x: (x["status"] != "Active", x["name"]))
    st.session_state.unassigned_others.sort(key=lambda x: x["name"])
    
    st.session_state.commits = [c for c in st.session_state.commits if c['id'] != commit_id]
    
    st.session_state.hist_probs = copy.deepcopy(st.session_state.original_hist_probs)
    for c in st.session_state.commits:
        if c.get("is_new", False):
            st.session_state.hist_probs.append({'title': c['title'], 'full_content': c['full_text']})
        else:
            for p in st.session_state.hist_probs:
                if p['title'] == c['title']:
                    p['full_content'] = parse_and_merge_updates(p['full_content'], c['content'])
                    break
                    
    final_blocks = []
    for idx, p in enumerate(st.session_state.hist_probs):
        content = p['full_content'].strip()
        content = re.sub(r'^\d+\.\s*', '', content)
        final_blocks.append(f"{idx+1}. {content}")
    st.session_state.final_text = "\n\n".join(final_blocks)

# =========================
#  Streamlit Web UI
# =========================
st.set_page_config(page_title="SOAP Direct Assign", layout="wide")
st.title("🏥 SOAP Generator (多來源匯入版)")

steps = ["1️⃣ Upload/Paste", "2️⃣ Assign & Edit", "3️⃣ Final Push"]
st.progress((st.session_state.step - 1) / 2)
st.write(f"**Current Phase：{steps[st.session_state.step - 1]}**")
st.divider()

# =========================
#  Phase 1：Upload & Paste
# =========================
if st.session_state.step == 1:
    col_up1, col_up2 = st.columns(2)
    
    with col_up1:
        st.markdown("#### 📚 1. 匯入歷史 SOAP")
        tab_soap_text, tab_soap_file = st.tabs(["📋 直接貼上", "📁 上傳檔案"])
        with tab_soap_text:
            pasted_soap = st.text_area("在此貼上 SOAP 文字內容：", height=200, key="soap_text")
        with tab_soap_file:
            uploaded_soap = st.file_uploader("或上傳 soap_input.txt", type=['txt'], key="soap_file")

    with col_up2:
        st.markdown("#### 📝 2. 匯入今日醫囑 Log")
        tab_log_text, tab_log_file = st.tabs(["📋 直接貼上", "📁 上傳檔案 (可複選)"])
        with tab_log_text:
            pasted_log = st.text_area("在此貼上 Log 文字內容：", height=200, key="log_text")
        with tab_log_file:
            uploaded_logs = st.file_uploader("或上傳 log_input.txt", type=['txt'], accept_multiple_files=True, key="log_file")

    st.write("") 
    
    col_p1, col_p2 = st.columns([5, 1])
    with col_p2:
        parse_btn = st.button("🚀 Parse & Init", type="primary", use_container_width=True)
        
    if parse_btn:
        soap_content = ""
        if pasted_soap.strip():
            soap_content = pasted_soap
        elif uploaded_soap:
            soap_content = uploaded_soap.read().decode("utf-8")

        all_log_lines = []
        if pasted_log.strip():
            all_log_lines.extend(pasted_log.split('\n'))
        if uploaded_logs:
            for log_file in uploaded_logs:
                all_log_lines.extend(log_file.read().decode("utf-8").split('\n'))

        if soap_content or all_log_lines:
            if soap_content:
                st.session_state.hist_probs, st.session_state.hist_plan = parse_historical_soap(soap_content)
                st.session_state.original_hist_probs = copy.deepcopy(st.session_state.hist_probs)
            
            if all_log_lines:
                entries = parse_logs_from_lines(all_log_lines)
                for e in entries: classify_entry(e)
                st.session_state.unassigned_meds, st.session_state.unassigned_others = process_logs(entries)
                
            st.session_state.step = 2
            st.rerun()
        else:
            st.error("請至少上傳一份檔案或貼上部分內容！")

# =========================
#  Phase 2：Assign & Edit
# =========================
elif st.session_state.step == 2:
    st.markdown("### 📌 1. 選擇目標病名 (Select Target Problem)")
    prob_options = [p['title'] for p in st.session_state.hist_probs] + ["➕ [建立新病名 / Create New Problem]"]
    selected_prob_title = st.radio("Target Problem:", prob_options, label_visibility="collapsed")
    
    base_text = "New Problem: \n" if selected_prob_title == "➕ [建立新病名 / Create New Problem]" else next((p['full_content'] for p in st.session_state.hist_probs if p['title'] == selected_prob_title), "")

    st.divider()
    st.markdown("### 🗂️ 2. 點擊分配類別 (Click to Assign)")
    col_pool, col_stage = st.columns([1.5, 1])
    
    with col_pool:
        st.markdown("##### 📦 未分配醫囑")
        for m in st.session_state.unassigned_meds:
            c1, c2, c3, c4, c5 = st.columns([4, 1, 1, 1, 1])
            c1.markdown(f"💊 **{m['display']}**")
            c2.button("Exam", key=f"me_{m['name']}", on_click=stage_item, args=('med', m, "[Exam]"))
            c3.button("Past", key=f"mp_{m['name']}", on_click=stage_item, args=('med', m, "[Past treatment]"))
            c4.button("Cur", key=f"mc_{m['name']}", on_click=stage_item, args=('med', m, "[Current Management]"))
            c5.button("Cons", key=f"mco_{m['name']}", on_click=stage_item, args=('med', m, "[Consult]"))

        for o in st.session_state.unassigned_others:
            c1, c2, c3, c4, c5 = st.columns([4, 1, 1, 1, 1])
            c1.markdown(f"🔬 **{o['display']}**")
            c2.button("Exam", key=f"oe_{o['name']}", on_click=stage_item, args=('other', o, "[Exam]"))
            c3.button("Past", key=f"op_{o['name']}", on_click=stage_item, args=('other', o, "[Past treatment]"))
            c4.button("Cur", key=f"oc_{o['name']}", on_click=stage_item, args=('other', o, "[Current Management]"))
            c5.button("Cons", key=f"oco_{o['name']}", on_click=stage_item, args=('other', o, "[Consult]"))

    with col_stage:
        st.markdown("##### 🛒 購物車")
        for cat in ["[Exam]", "[Past treatment]", "[Current Management]", "[Consult]"]:
            if st.session_state.staged[cat]:
                st.markdown(f"**{cat}**")
                for item in st.session_state.staged[cat]:
                    c_name, c_btn = st.columns([4, 1])
                    c_name.write(f"- {item['data']['display']}")
                    c_btn.button("❌", key=f"del_{id(item)}", on_click=unstage_item, args=(cat, item))

    st.divider()
    
    st.markdown("### ✍️ 3. 補充今日理由 (Edit New Indications)")
    # 【版面調整】將「可自由反白複製」的提示上收到此處，維持下方左右兩欄的高低對齊
    st.warning("💡 左側為舊紀錄供對照（**可自由反白複製，修改不會被儲存**）；請直接在右側為剛加入的醫囑補充理由（⚠️ **請勿修改 [括號] 名稱**）。")
    
    new_update_lines = []
    reference_details = [] 
    
    for cat in ["[Exam]", "[Past treatment]", "[Current Management]", "[Consult]"]:
        items = st.session_state.staged[cat]
        if items:
            new_update_lines.append(cat)
            for item in items:
                disp = item['data']['display']
                details = item['data']['details']
                
                if cat in ["[Current Management]", "[Past treatment]"]:
                    if "[DC]" in disp: new_update_lines.append(f"- {disp} due to ____________")
                    else: new_update_lines.append(f"- {disp} for ____________")
                elif cat == "[Consult]": new_update_lines.append(f"- F/U {disp}")
                else: new_update_lines.append(f"- {disp}")
                
                reference_details.append(f"**{disp}**\n> `{details}`")
                
            new_update_lines.append("") 
            
    initial_updates = "\n".join(new_update_lines).strip()
    
    col_old, col_new = st.columns(2)
    
    with col_old:
        st.markdown("##### 📜 原歷史病歷 (對照用)")
        st.text_area("舊紀錄：", value=base_text, height=300, label_visibility="collapsed")
        
    with col_new:
        st.markdown("##### 🆕 本次新增 (請在此編輯)")
        current_edit = st.text_area("本次更新內容：", value=initial_updates, height=300, label_visibility="collapsed")
    
    if reference_details:
        st.info("🔎 **醫囑詳細資料參考區**\n\n" + "\n\n".join(reference_details))
    
    st.write("")
    
    col_b1, col_b2, col_b3 = st.columns([1, 4, 2])
    with col_b1:
         if st.button("🗑️ Reset All"): reset_app()
    with col_b2:
         if st.button("💾 Commit 更新此病名 (原地儲存)", type="primary", use_container_width=True):
             final_problem_text = parse_and_merge_updates(base_text, current_edit)
             
             is_new = (selected_prob_title == "➕ [建立新病名 / Create New Problem]")
             actual_title = selected_prob_title
             
             if is_new:
                 first_line = final_problem_text.strip().split('\n')[0]
                 actual_title = first_line if len(first_line) > 2 else f"New Problem {len(st.session_state.hist_probs)+1}"
                 st.session_state.hist_probs.append({'title': actual_title, 'full_content': final_problem_text})
             else:
                 for p in st.session_state.hist_probs:
                     if p['title'] == selected_prob_title:
                         p['full_content'] = final_problem_text
                         break
             
             st.session_state.commits.append({
                 "id": st.session_state.commit_counter,
                 "title": actual_title,
                 "is_new": is_new,
                 "content": current_edit if current_edit.strip() else "(無新增內容)",
                 "full_text": final_problem_text,
                 "used_items": copy.deepcopy(st.session_state.staged)
             })
             st.session_state.commit_counter += 1
             
             for cat in st.session_state.staged: st.session_state.staged[cat].clear()
             st.success("✅ 此病歷段落已更新！您可以繼續編輯其他病名。")
             st.rerun()
    with col_b3:
         btn_text = "🚀 Push All (前往核對)" if not st.session_state.unassigned_meds and not st.session_state.unassigned_others else "⚠️ Push (尚有未分配)"
         if st.button(btn_text, use_container_width=True):
             final_blocks = []
             for idx, p in enumerate(st.session_state.hist_probs):
                 content = p['full_content'].strip()
                 content = re.sub(r'^\d+\.\s*', '', content)
                 final_blocks.append(f"{idx+1}. {content}")
             
             st.session_state.final_text = "\n\n".join(final_blocks)
             st.session_state.step = 3
             st.rerun()

# =========================
#  Phase 3：Push
# =========================
elif st.session_state.step == 3:
    col_title, col_btn_top = st.columns([4, 1])
    with col_title:
        st.subheader("🚀 Phase 3: Final Review & Push")
    with col_btn_top:
        st.button("🔄 Start New Patient", on_click=reset_app, type="secondary", key="reset_top")
        
    if not st.session_state.final_text.strip():
        st.warning("You haven't initialized the text.")
    else:
        st.success("🎉 所有病歷已彙整完畢！您可以直接在下方做最後微調。")
    
    if st.session_state.commits:
        st.markdown("#### 📜 本次更新摘要 (Commits Summary)")
        st.caption("您可以檢視或刪除今天加入的 Commit。刪除後，該醫囑會退回 Phase 2 的未分配清單。")
        for c in reversed(st.session_state.commits):
            with st.expander(f"✏️ {c['title']} (Commit #{c['id']})", expanded=False):
                st.text(c['content'])
                if st.button("🗑️ 撤銷此 Commit (退回醫囑)", key=f"del_commit_{c['id']}"):
                    delete_commit(c['id'])
                    st.toast(f"已撤銷 Commit #{c['id']} 並退回關聯醫囑！", icon="🗑️")
                    st.rerun()
        st.divider()

    plan_updates = []
    for c in st.session_state.commits:
        content_text = c['content']
        clean_title = re.sub(r'^\d+\.\s*', '', c['title'])
        
        blocks = []
        match_cm = re.search(r'\[\s*Current Management\s*\](.*?)(?=\n\s*\[|\Z)', content_text, re.DOTALL | re.IGNORECASE)
        if match_cm and match_cm.group(1).strip():
            blocks.append("[Current Management]\n" + match_cm.group(1).strip())
            
        match_cs = re.search(r'\[\s*Consult\s*\](.*?)(?=\n\s*\[|\Z)', content_text, re.DOTALL | re.IGNORECASE)
        if match_cs and match_cs.group(1).strip():
            blocks.append("[Consult]\n" + match_cs.group(1).strip())
            
        if blocks:
            plan_updates.append(f"{clean_title}\n" + "\n".join(blocks))
                
    combined_plan = st.session_state.hist_plan.strip() if st.session_state.hist_plan else ""
    if plan_updates:
        if combined_plan:
            combined_plan += "\n\n"
        combined_plan += "\n\n".join(plan_updates)

    st.markdown("##### 📝 Assessment (A)")
    edited_final_a_text = st.text_area(
        "A 段落：",
        value=st.session_state.final_text,
        height=400,
        label_visibility="collapsed"
    )
    
    st.markdown("##### 📝 Plan (P)")
    edited_final_p_text = st.text_area(
        "P 段落：",
        value=combined_plan.strip(),
        height=300,
        label_visibility="collapsed"
    )
    
    final_download_content = f"A:\n{edited_final_a_text}\n\nP:\n{edited_final_p_text}"
    
    st.write("")
    
    col_dl1, col_dl2, col_dl3 = st.columns([1, 4, 2])
    with col_dl1: 
        if st.button("⬅️ 返回修改 (Back)"):
            st.session_state.step = 2
            st.rerun()
        st.caption("⚠️ 退回將重置此頁修改")
    with col_dl3:
        st.download_button(
            "📥 Download Final A/P",
            data=final_download_content,
            file_name="SOAP_AP_Final.txt",
            mime="text/plain",
            type="primary",
            use_container_width=True
        )