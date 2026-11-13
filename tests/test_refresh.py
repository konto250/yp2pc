"""取得失敗時の継続と、削除されたフィードを復活させないことを検証します。"""
import unittest
from unittest.mock import patch
from yp2pc import refresh
from yp2pc.core import AppError


class RefreshTests(unittest.TestCase):
    def test_failed_refresh_does_not_stop_other_feeds(self):
        with patch.object(refresh.storage, "list_feeds", return_value=[{"id": "first"}, {"id": "second"}]), \
                patch.object(refresh.storage, "registered", return_value=True), \
                patch.object(refresh, "build_feed", side_effect=[AppError("接続失敗", 502), {}]) as build:
            refresh.refresh_once()
            self.assertEqual(build.call_count, 2)

    def test_deleted_feed_is_not_recreated(self):
        with patch.object(refresh.storage, "list_feeds", return_value=[{"id": "deleted"}]), \
                patch.object(refresh.storage, "registered", return_value=False), \
                patch.object(refresh, "build_feed") as build:
            refresh.refresh_once()
            build.assert_not_called()
