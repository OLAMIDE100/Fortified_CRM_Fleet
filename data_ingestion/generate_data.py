import sys


from data.customers_500_tuples import customers
from helper_scripts.db import get_connection




def create_leads_table(conn):
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id TEXT PRIMARY KEY,
        name TEXT,
        email TEXT,
        game_genre_preference TEXT,
        monthly_spend DOUBLE PRECISION,
        play_time_hours_wk DOUBLE PRECISION,
        status TEXT,
        qualification_score INTEGER,
        churn_risk_level TEXT,
        last_outreach TEXT
    )
    """)

    conn.commit()
    print("✓ Leads table created in Postgres.")


def load_leads_table(conn):

    cursor = conn.cursor()


    cursor.executemany(
        """
        INSERT INTO leads (
            id, name, email, game_genre_preference, monthly_spend,
            play_time_hours_wk, status, qualification_score,
            churn_risk_level, last_outreach
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            email = EXCLUDED.email,
            game_genre_preference = EXCLUDED.game_genre_preference,
            monthly_spend = EXCLUDED.monthly_spend,
            play_time_hours_wk = EXCLUDED.play_time_hours_wk,
            status = EXCLUDED.status,
            qualification_score = EXCLUDED.qualification_score,
            churn_risk_level = EXCLUDED.churn_risk_level,
            last_outreach = EXCLUDED.last_outreach
        """,
        customers,
    )

    conn.commit()
    print("✓ Leads table loaded in Postgres.")




def init_local_db():
    conn = get_connection()

    create_leads_table(conn)
    load_leads_table(conn)

    print("✓ Postgres CRM initialized with sample leads.")
    conn.close()


if __name__ == "__main__":
    init_local_db()
