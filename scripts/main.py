from rss_monitor import fetch_new_entries, mark_as_published
from content_transformer import transform_for_note
from note_publisher import publish_to_note


def main():
    print("アメブロの新記事をチェック中...")
    new_entries = fetch_new_entries()

    if not new_entries:
        print("新しい記事はありません")
        return

    print(f"{len(new_entries)}件の新記事を検出")

    for entry in new_entries:
        print(f"\n処理中: {entry['title']}")
        note_data = transform_for_note(entry["title"], entry["content"])

        print(f"  タイトル: {note_data['title']}")
        print(f"  ハッシュタグ: {' '.join(note_data['hashtags'])}")

        success = publish_to_note(
            title=note_data["title"],
            content=note_data["content"],
            hashtags=note_data["hashtags"],
        )

        if success:
            mark_as_published(entry["id"])
        else:
            print(f"投稿失敗（スキップ）: {entry['title']}")


if __name__ == "__main__":
    main()
