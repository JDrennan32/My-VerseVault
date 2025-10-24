# VerseVault — Single-User Streamlit App (Finalized Fill-in-the-Blank Quiz)
from __future__ import annotations
import streamlit as st
import pandas as pd
import random
import re
import sqlite3
from datetime import datetime
from pathlib import Path

# ---- Page config & robust asset handling ----
APP_DIR = Path(__file__).parent
ASSETS_DIR = APP_DIR / "assets"
SPLASH_IMAGE_FILE = "VV_Homepage.png"
SMALL_LOGO_FILE = "VV_SmallLogo.png"
SPLASH_IMAGE_PATH = ASSETS_DIR / SPLASH_IMAGE_FILE
SMALL_LOGO_PATH = ASSETS_DIR / SMALL_LOGO_FILE


def _read_bytes_safe(path: Path):
    try:
        return path.read_bytes() if path.exists() else None
    except Exception:
        return None


def configure_page():
    icon_bytes = _read_bytes_safe(SMALL_LOGO_PATH)
    try:
        if icon_bytes is not None:
            st.set_page_config(page_title="VerseVault", page_icon=icon_bytes, layout="wide")
        else:
            st.set_page_config(page_title="VerseVault", page_icon="📖", layout="wide")
    except Exception:
        # set_page_config may already be called on rerun
        pass


def show_splash():
    """Render the homepage splash image with a graceful fallback."""
    img_bytes = _read_bytes_safe(SPLASH_IMAGE_PATH)

    # Optional hosted fallback via secrets
    splash_url = st.secrets.get("branding", {}).get("splash_url") if hasattr(st, "secrets") else None
    if img_bytes is not None:
        st.image(img_bytes, use_container_width=True)
    elif splash_url:
        st.image(splash_url, use_container_width=True)
    else:
        st.header("Welcome to VerseVault!")
        st.caption(f"(Splash image missing — expected: {SPLASH_IMAGE_PATH})")


configure_page()

@st.cache_resource(show_spinner=False)
def get_storage():
    try:
        sb = st.secrets.get("supabase", None)
        if sb and (sb.get("url") or sb.get("URL")):
            from supabase import create_client
            url = sb.get("url") or sb.get("URL")
            key = (
                sb.get("key") or sb.get("anon") or sb.get("anon_key") or sb.get("api_key")
                or sb.get("apikey") or sb.get("public_key") or sb.get("PUBLIC_ANON_KEY")
            )
            if url and key:
                return SupabaseStorage(create_client(url, key))
    except Exception:
        pass
    return SQLiteStorage()


class SupabaseStorage:
    def __init__(self, client):
        self.client = client
        self.backend = "supabase"
        self.verses = "vv_verses"
        self.future = "vv_future_verses"

    def list_verses(self):
        res = (self.client
                 .table(self.verses)
                 .select("*")
                 .order("created_at", desc=True)
                 .order("id", desc=True)
                 .execute())
        return pd.DataFrame(res.data or [])

    def add_verse(self, ref, text, explanation, translation):
        self.client.table(self.verses).insert({"ref": ref, "text": text, "explanation": explanation, "translation": translation}).execute()

    def update_verse(self, id_, ref, text, explanation, translation):
        self.client.table(self.verses).update({"ref": ref, "text": text, "explanation": explanation, "translation": translation}).eq("id", id_).execute()

    def list_future(self):
        res = self.client.table(self.future).select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(res.data or [])

    def add_future(self, ref):
        self.client.table(self.future).insert({"ref": ref}).execute()

    def remove_future(self, id_):
        self.client.table(self.future).delete().eq("id", id_).execute()


class SQLiteStorage:
    def __init__(self):
        self.backend = "sqlite"
        self.conn = sqlite3.connect("vv_local.db", check_same_thread=False)
        self._init()

    def _init(self):
        cur = self.conn.cursor()
        cur.execute("""
            create table if not exists vv_verses (
                id integer primary key autoincrement,
                ref text not null,
                text text not null,
                explanation text,
                translation text,
                created_at text default (datetime('now'))
            )
        """)
        cur.execute("""
            create table if not exists vv_future_verses (
                id integer primary key autoincrement,
                ref text not null,
                created_at text default (datetime('now'))
            )
        """)
        self.conn.commit()

    def add_verse(self, ref, text, explanation, translation):
        self.conn.execute("insert into vv_verses(ref, text, explanation, translation) values(?,?,?,?)", (ref, text, explanation, translation))
        self.conn.commit()

    def update_verse(self, id_, ref, text, explanation, translation):
        self.conn.execute("update vv_verses set ref=?, text=?, explanation=?, translation=? where id= ?", (ref, text, explanation, translation, id_))
        self.conn.commit()

    def list_verses(self):
        return pd.read_sql_query("select * from vv_verses order by datetime(created_at) desc, id desc", self.conn)

    def add_future(self, ref):
        self.conn.execute("insert into vv_future_verses(ref) values(?)", (ref,))
        self.conn.commit()

    def list_future(self):
        return pd.read_sql_query("select * from vv_future_verses order by datetime(created_at) desc, id desc", self.conn)

    def remove_future(self, id_):
        self.conn.execute("delete from vv_future_verses where id=?", (id_,))
        self.conn.commit()


storage = get_storage()

# ---------- SIDEBAR ----------
with st.sidebar:
    # Sidebar logo with safe-bytes loader
    logo_bytes = _read_bytes_safe(SMALL_LOGO_PATH)
    if logo_bytes is not None:
        st.image(logo_bytes, use_container_width=True)
    else:
        st.markdown("### VerseVault")

    st.markdown("### Welcome to VerseVault!")
    st.caption("Build a personal vault of verses, review them with smart quizzes, and keep Scripture at the center of your week.")
    st.divider()
    st.markdown(f"""**Storage:** {storage.backend.upper()}  

(Supabase if secrets provided; otherwise local SQLite.)""")
    if st.button("Reconnect Supabase", use_container_width=True):
        st.cache_resource.clear()
        st.rerun()

# ---------- HOME ----------
if "entered" not in st.session_state:
    st.session_state.entered = False

if not st.session_state.entered:
    show_splash()
    if st.button("Enter Vault", type="primary", use_container_width=True):
        st.session_state.entered = True
        st.rerun()
    st.stop()

# ---------- MAIN TABS ----------
vt, qt, ft, mt = st.tabs(["Vault", "Quiz", "Future Verses", "Manage Vault"])

# ----- VAULT -----
with vt:
    st.subheader("Your Verse Vault")
    df = storage.list_verses()
    if df.empty:
        st.info("No verses yet. Add one in Manage Vault.")
    else:
        for _, r in df.iterrows():
            with st.expander(r["ref"]):
                st.write(r["text"])
                if r.get("explanation"): st.write(r["explanation"])

# ----- QUIZ -----
with qt:
    st.subheader("Quiz")
    df_all = storage.list_verses()
    if df_all.empty:
        st.info("Add at least one verse to use the quiz.")
    else:
        mem_tab, fill_tab = st.tabs(["Memorization (Newest → Oldest)", "Fill in the Blank (Random)"])

        # Stable widget-key epoch to avoid duplicate keys across states
        if "quiz_epoch" not in st.session_state:
            st.session_state.quiz_epoch = 0

        # Prepare verse id list (deterministic newest→oldest)
        ids_desc = df_all["id"].tolist()

        # --- Memorization: deterministic order, preserve position across reruns ---
        if "mem_ids" not in st.session_state:
            st.session_state.mem_ids = ids_desc[:]
            st.session_state.mem_pos = 0
        else:
            # Only rebuild if the SET of ids changed (added/removed). Keep position by current id.
            if set(st.session_state.mem_ids) != set(ids_desc):
                current_id = None
                if st.session_state.mem_ids:
                    # clamp mem_pos
                    st.session_state.mem_pos = min(st.session_state.mem_pos, len(st.session_state.mem_ids)-1)
                    current_id = st.session_state.mem_ids[st.session_state.mem_pos]
                st.session_state.mem_ids = ids_desc[:]
                # move pointer to same verse if still present
                if current_id in st.session_state.mem_ids:
                    st.session_state.mem_pos = st.session_state.mem_ids.index(current_id)
                else:
                    st.session_state.mem_pos = 0

        # --- Fill-in-the-blank: keep a fixed shuffle for the session; rebuild only when set changes ---
        if "fib_ids" not in st.session_state:
            fib = ids_desc[:]
            random.shuffle(fib)
            st.session_state.fib_ids = fib
            st.session_state.fib_pos = 0
        else:
            if set(st.session_state.fib_ids) != set(ids_desc):
                fib = ids_desc[:]
                random.shuffle(fib)
                st.session_state.fib_ids = fib
                st.session_state.fib_pos = 0

        # Helper to get row by id
        def _get_row_by_id(vid):
            return df_all[df_all["id"] == vid].iloc[0]

        # -------------------- MEMORIZATION --------------------
        with mem_tab:
            cur_id = st.session_state.mem_ids[st.session_state.mem_pos]
            cur = _get_row_by_id(cur_id)
            st.write(f"**Verse:** {cur['ref']}")

            epoch = st.session_state.quiz_epoch
            # Persist results visibility across reruns
            mem_flag_key = f"mem_show_{cur_id}"

            with st.form(f"mem_form_{cur_id}_{epoch}"):
                mem_text = st.text_area("Type out the verse from memory:", key=f"mem_ta_{cur_id}_{epoch}")
                mem_submitted = st.form_submit_button("Submit (Memorization)")

            if mem_submitted:
                st.session_state[mem_flag_key] = True
                st.session_state[f"mem_text_{cur_id}"] = mem_text

            if st.session_state.get(mem_flag_key, False):
                st.write("### Your Answer:")
                st.info(st.session_state.get(f"mem_text_{cur_id}", ""))
                st.write("### Correct Verse:")
                st.success(cur['text'])
                if st.button("Next (Memorization)", key=f"mem_next_{cur_id}_{epoch}"):
                    st.session_state.mem_pos = (st.session_state.mem_pos + 1) % len(st.session_state.mem_ids)
                    # reset state for current verse and bump epoch so widget keys rotate
                    st.session_state[mem_flag_key] = False
                    st.session_state.pop(f"mem_text_{cur_id}", None)
                    st.session_state.quiz_epoch += 1
                    st.rerun()

        # ----------------- FILL IN THE BLANK -----------------
        with fill_tab:
            cur_id = st.session_state.fib_ids[st.session_state.fib_pos]
            cur = _get_row_by_id(cur_id)

            words = cur["text"].split()
            n = len(words)
            if n <= 15:
                num_blanks = 3
            elif n <= 30:
                num_blanks = 5
            else:
                num_blanks = 7

            # Keep per-verse blanks so they don't change while typing
            if "fb_blanks_per_id" not in st.session_state:
                st.session_state.fb_blanks_per_id = {}
            if cur_id not in st.session_state.fb_blanks_per_id:
                choose = min(num_blanks, n)
                st.session_state.fb_blanks_per_id[cur_id] = sorted(random.sample(range(n), choose))
            blank_indices = st.session_state.fb_blanks_per_id[cur_id]

            # Build prompt and answer map (strip punctuation from answers)
            blank_map = {}
            prompt_words = words[:]
            for i, idx in enumerate(blank_indices, start=1):
                clean = re.sub(r"[.,;:!?]", "", words[idx])
                blank_map[f"[{i}]"] = clean
                prompt_words[idx] = f"[{i}]"

            st.write(f"**Verse:** {cur['ref']}")
            st.markdown(" ".join(prompt_words))

            epoch = st.session_state.quiz_epoch
            fib_flag_key = f"fib_show_{cur_id}"

            with st.form(f"fib_form_{cur_id}_{epoch}"):
                answers = {}
                for i in range(1, len(blank_indices) + 1):
                    answers[i] = st.text_input(f"Answer for [{i}]", key=f"fib_ans_{cur_id}_{i}_{epoch}")
                fib_submitted = st.form_submit_button("Submit (Fill in the Blank)")

            if fib_submitted:
                # Cache results so they persist across reruns until Next
                results = []
                for tag, correct in blank_map.items():
                    i = int(tag.strip("[]"))
                    user_answer = answers.get(i, "")
                    ok = re.sub(r"[.,;:!?]", "", user_answer.lower().strip()) == correct.lower()
                    results.append((tag, user_answer, correct, ok))
                st.session_state[f"fib_results_{cur_id}"] = results
                st.session_state[fib_flag_key] = True

            if st.session_state.get(fib_flag_key, False):
                st.write("### Results:")
                for tag, user_answer, correct, ok in st.session_state.get(f"fib_results_{cur_id}", []):
                    if ok:
                        st.success(f"{tag}: {user_answer} ✅")
                    else:
                        st.error(f"{tag}: {user_answer} ❌ (Correct: {correct})")
                if st.button("Next (Fill in the Blank)", key=f"fib_next_{cur_id}_{epoch}"):
                    st.session_state.fib_pos = (st.session_state.fib_pos + 1) % len(st.session_state.fib_ids)
                    # regenerate blanks next time this verse appears & clear cached results
                    st.session_state.fb_blanks_per_id.pop(cur_id, None)
                    st.session_state.pop(f"fib_results_{cur_id}", None)
                    st.session_state[fib_flag_key] = False
                    st.session_state.quiz_epoch += 1
                    st.rerun()

# ----- FUTURE VERSES -----
with ft:
    st.subheader("Future Verses")
    new = st.text_input("Add verse reference")
    if st.button("Add Future Verse") and new.strip():
        storage.add_future(new)
        st.success(f"Added {new}")
        st.rerun()
    df2 = storage.list_future()
    if not df2.empty:
        for _, row in df2.iterrows():
            cols = st.columns([5, 1])
            cols[0].markdown(f"- **{row['ref']}**")
            if cols[1].button("Remove", key=f"remove_{row['id']}"):
                storage.remove_future(row['id'])
                st.rerun()
    else:
        st.info("No future verses yet. Add one above.")

# ----- MANAGE VAULT -----
with mt:
    st.subheader("Manage Vault")
    add_tab, edit_tab = st.tabs(["Add Verse", "Edit Verse"])

    with add_tab:
        ref = st.text_input("Verse Reference")
        text = st.text_area("Verse Text")
        exp = st.text_area("Explanation")
        trans = st.text_input("Translation")
        if st.button("Add Verse") and ref and text:
            storage.add_verse(ref, text, exp, trans)
            st.success(f"Added {ref} to your vault!")

    with edit_tab:
        df_edit = storage.list_verses()
        if df_edit.empty:
            st.info("No verses to edit yet.")
        else:
            selected = st.selectbox("Select a verse to edit", df_edit["ref"].tolist())
            verse_row = df_edit[df_edit["ref"] == selected].iloc[0]

            new_ref = st.text_input("Edit Reference", verse_row["ref"])
            new_text = st.text_area("Edit Verse Text", verse_row["text"])
            new_exp = st.text_area("Edit Explanation", verse_row.get("explanation", ""))
            new_trans = st.text_input("Edit Translation", verse_row.get("translation", ""))

            if st.button("Save Changes"):
                storage.update_verse(verse_row["id"], new_ref, new_text, new_exp, new_trans)
                st.success(f"Updated {new_ref} successfully!")
                st.rerun()
