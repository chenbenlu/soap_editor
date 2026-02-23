# 🏥 SOAP Generator (Secure Local Edition)

This is a clinical SOAP note writing assistant designed specifically for physicians. Utilizing WebAssembly (`stlite`) technology, it packages the entire Streamlit Python environment directly into the front-end browser. **All patient data parsing and processing are completed within the local computer's memory, achieving a strict 100% Zero Data Leakage medical security standard.**

## ✨ Core Features

* **Pure Frontend Computing (No Backend):** No backend server is required. It can be directly deployed on GitHub Pages, bypassing hospital HIS systems and strict IT network restrictions.
* **Smart Multi-Source Import:** Supports one-click pasting of "Historical SOAP" and "Today's Medical Orders (Logs)", with automatic normalization of medication and treatment names (Title Case).
* **Split-View Editing:** The left panel locks the historical medical record as read-only (supports highlighting and copying) for reference, while the right panel allows focused editing of today's new medical orders, significantly reducing cognitive load.
* **Commit Version Control System:** Manages medical record updates like Git. Supports reviewing history, a "One-Click Revert" function, and dynamically returning unassigned orders.
* **Dynamic Plan (P) Generation:** Strictly extracts `[Current Management]` and `[Consult]` from today's Commits to accurately generate the handover Plan (To-do list).

---

## 🚀 Live Demo

Click the link below to start using it (Initial loading requires 10~30 seconds to download the Python engine):
https://chenbenlu.github.io/soap_editor/
