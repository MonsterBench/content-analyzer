"""Migration script: Import existing williamdperryiii reel data into SQLite."""

import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session
from backend.models.database import (
    Creator, Platform, ContentItem, create_db_and_tables, engine,
)


def parse_timestamp(ts) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts)
        except (OSError, ValueError):
            pass
    return None


def migrate():
    # Look in parent directory (../instagram_reel_analyzer/) since the old project is a sibling
    processed_file = Path(__file__).parent.parent.parent / "instagram_reel_analyzer" / "reel_data" / "williamdperryiii_processed.json"

    if not processed_file.exists():
        print(f"Data file not found: {processed_file}")
        print("Skipping migration - no existing data to import.")
        return

    print(f"Loading data from {processed_file}...")
    with open(processed_file, "r", encoding="utf-8") as f:
        reels = json.load(f)

    print(f"Found {len(reels)} reels to migrate")

    # Create tables
    create_db_and_tables()

    with Session(engine) as db:
        # Check if creator already exists
        from sqlmodel import select
        existing = db.exec(
            select(Creator).where(Creator.name == "William Perry III")
        ).first()

        if existing:
            print("Creator 'William Perry III' already exists. Skipping migration.")
            return

        # Create the creator
        creator = Creator(
            name="William Perry III",
            schedule_frequency="manual",
        )
        db.add(creator)
        db.commit()
        db.refresh(creator)
        print(f"Created creator: {creator.name} (id={creator.id})")

        # Create IG platform
        platform = Platform(
            creator_id=creator.id,
            type="instagram",
            handle="williamdperryiii",
            url="https://www.instagram.com/williamdperryiii/",
        )
        db.add(platform)
        db.commit()
        db.refresh(platform)
        print(f"Created platform: instagram @{platform.handle} (id={platform.id})")

        # Import reels
        imported = 0
        for reel in reels:
            item = ContentItem(
                platform_id=platform.id,
                type="instagram_reel",
                external_id=reel.get("shortCode") or reel.get("id", f"reel_{imported}"),
                url=reel.get("url", ""),
                title=None,
                caption=reel.get("caption", ""),
                transcript=reel.get("transcript", reel.get("caption", "")),
                transcript_source=reel.get("transcript_source", "caption_fallback"),
                timestamp=parse_timestamp(reel.get("timestamp")),
                likes=reel.get("likes", 0) or 0,
                comments=reel.get("comments", 0) or 0,
                views=reel.get("plays", 0) or 0,
                duration=reel.get("duration", 0) or 0.0,
                tags=str(reel.get("hashtags", [])),
                is_embedded=False,
            )
            db.add(item)
            imported += 1

        db.commit()
        print(f"Imported {imported} reels into SQLite")

        # Update platform last_scraped_at
        platform.last_scraped_at = datetime.utcnow()
        creator.last_scraped_at = datetime.utcnow()
        db.add(platform)
        db.add(creator)
        db.commit()

    print("Migration complete!")


if __name__ == "__main__":
    migrate()
