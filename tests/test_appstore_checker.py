"""appstore_checkerの通知判定テスト。"""

from datetime import date, datetime

from src.appstore_checker import (
    AppSummary,
    BuildMessage,
    BuildNotificationTargets,
    CalculateNextRun,
    ParseApps,
    ParsePreOrderApp,
    PreOrderApp,
)


def test_build_notification_targets_within_notify_window() -> None:
    """予定日の7日前から当日まで通知対象になることを確認する。"""

    apps = [
        PreOrderApp(
            "company-a",
            "1",
            "Target App",
            "com.example.target",
            date(2026, 5, 8),
            ("JPN",),
            ("AVAILABLE_FOR_PREORDER",),
        ),
        PreOrderApp(
            "company-a",
            "2",
            "Future App",
            "com.example.future",
            date(2026, 5, 9),
            ("JPN",),
            ("AVAILABLE_FOR_PREORDER",),
        ),
    ]

    targets = BuildNotificationTargets(
        apps=apps,
        today=date(2026, 5, 1),
        notify_days=7,
        state={},
    )

    assert [target.app.app_id for target in targets] == ["1"]


def test_build_notification_targets_skips_already_notified_today() -> None:
    """同じ日に同じアプリへ重複通知しないことを確認する。"""

    apps = [
        PreOrderApp(
            "company-a",
            "1",
            "Target App",
            "com.example.target",
            date(2026, 5, 8),
            ("JPN",),
            ("AVAILABLE_FOR_PREORDER",),
        )
    ]

    state = {"company-a:1:2026-05-08": "2026-05-01"}

    targets = BuildNotificationTargets(
        apps=apps,
        today=date(2026, 5, 1),
        notify_days=7,
        state=state,
    )

    assert targets == []


def test_parse_pre_order_app_uses_earliest_release_date() -> None:
    """予約注文中テリトリの最短リリース日を通知対象日にする。"""

    app = AppSummary("1", "Target App", "com.example.target")
    data = {
        "included": [
            {
                "type": "territoryAvailabilities",
                "attributes": {
                    "preOrderEnabled": True,
                    "releaseDate": "2026-05-08",
                    "contentStatuses": ["AVAILABLE_FOR_PREORDER"],
                },
                "relationships": {"territory": {"data": {"id": "JPN"}}},
            },
            {
                "type": "territoryAvailabilities",
                "attributes": {
                    "preOrderEnabled": True,
                    "releaseDate": "2026-05-10",
                    "contentStatuses": ["AVAILABLE_FOR_PREORDER"],
                },
                "relationships": {"territory": {"data": {"id": "USA"}}},
            },
        ]
    }

    pre_order_app = ParsePreOrderApp("company-a", app, data)

    assert pre_order_app is not None
    assert pre_order_app.release_date == date(2026, 5, 8)
    assert pre_order_app.territories == ("JPN", "USA")


def test_parse_apps_reads_app_summary() -> None:
    """アプリ一覧レスポンスから名前とBundle IDを取得する。"""

    apps = ParseApps(
        {
            "data": [
                {
                    "id": "1",
                    "attributes": {
                        "name": "Target App",
                        "bundleId": "com.example.target",
                    },
                }
            ]
        }
    )

    assert apps == [AppSummary("1", "Target App", "com.example.target")]


def test_build_message_contains_company_code() -> None:
    """通知本文に会社コードと予定日が含まれることを確認する。"""

    app = PreOrderApp(
        "company-a",
        "1",
        "Target App",
        "com.example.target",
        date(2026, 5, 8),
        ("JPN",),
        ("AVAILABLE_FOR_PREORDER",),
    )
    targets = BuildNotificationTargets([app], date(2026, 5, 1), 7, {})

    message = BuildMessage(targets, date(2026, 5, 1))

    assert "company-a" in message
    assert "Target App" in message
    assert "2026-05-08" in message


def test_calculate_next_run_returns_tomorrow_after_poll_time() -> None:
    """指定時刻を過ぎている場合は翌日の実行時刻を返す。"""

    next_run = CalculateNextRun(datetime(2026, 5, 1, 10, 0), "09:00")

    assert next_run == datetime(2026, 5, 2, 9, 0)
