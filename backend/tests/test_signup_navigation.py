import unittest
from unittest import mock

from playwright.sync_api import TimeoutError as BrowserNavigationTimeout

from backend.registration import signup_flow


class SignupNavigationTests(unittest.TestCase):
    def setUp(self):
        self.page = mock.Mock()
        self.page.url = signup_flow.SIGNUP_URL
        self.browser = mock.Mock()
        self.browser.get_tabs.return_value = [self.page]
        self.logs = []
        self.cancel_callback = mock.Mock(return_value=False)
        self.hooks = {}
        for name, kwargs in {
            "active_browser": {"return_value": self.browser},
            "active_page": {"return_value": self.page},
            "set_browser_session": {},
            "_prepare_exit_ip": {},
            "start_browser": {},
            "restart_browser": {},
            "stop_browser": {},
            "sleep_with_cancel": {},
            "raise_if_cancelled": {},
            "click_email_signup_button": {},
        }.items():
            patcher = mock.patch.object(signup_flow, name, **kwargs)
            self.hooks[name] = patcher.start()
            self.addCleanup(patcher.stop)

    def navigate(self):
        signup_flow.open_signup_page(
            log_callback=self.logs.append,
            cancel_callback=self.cancel_callback,
        )

    def test_waits_for_dom_then_checks_entry_without_waiting_for_load(self):
        self.navigate()

        self.page.get.assert_called_once_with(
            signup_flow.SIGNUP_URL,
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        self.page.wait.doc_loaded.assert_not_called()
        self.hooks["click_email_signup_button"].assert_called_once_with(
            log_callback=self.logs.append,
            cancel_callback=self.cancel_callback,
        )
        self.hooks["restart_browser"].assert_not_called()

    def test_timeout_retries_once_with_the_same_bounded_dom_wait(self):
        self.page.get.side_effect = [BrowserNavigationTimeout("fixture"), None]

        self.navigate()

        self.assertEqual(self.page.get.call_count, 2)
        for call in self.page.get.call_args_list:
            self.assertEqual(call.kwargs["wait_until"], "domcontentloaded")
            self.assertEqual(call.kwargs["timeout"], 30_000)
        self.hooks["restart_browser"].assert_called_once()
        self.hooks["click_email_signup_button"].assert_called_once()
        self.assertTrue(any("DOMContentLoaded" in line for line in self.logs))
        self.assertTrue(any("不是 URL 格式错误" in line for line in self.logs))

    def test_two_timeouts_close_browser_and_do_not_continue(self):
        self.page.get.side_effect = BrowserNavigationTimeout("fixture")

        with self.assertRaisesRegex(Exception, "注册页加载超时：重试后"):
            self.navigate()

        self.assertEqual(self.page.get.call_count, 2)
        self.hooks["restart_browser"].assert_called_once()
        self.hooks["stop_browser"].assert_called_once()
        self.hooks["click_email_signup_button"].assert_not_called()

    def test_rejects_blank_error_pages_and_misleading_urls(self):
        for url in (
            "about:blank",
            "about:neterror",
            "http://accounts.x.ai/sign-up",
            "https://accounts.x.ai.example.invalid/sign-up",
            "https://example.invalid/?next=https://accounts.x.ai/sign-up",
            "https://accounts.x.ai@example.invalid/sign-up",
        ):
            with self.subTest(url=url):
                self.page.url = url
                with self.assertRaisesRegex(Exception, "预期的 HTTPS 注册域"):
                    self.navigate()
        self.hooks["click_email_signup_button"].assert_not_called()

    def test_dom_loaded_does_not_bypass_entry_readiness(self):
        self.hooks["click_email_signup_button"].side_effect = RuntimeError(
            "entry not ready"
        )

        with self.assertRaisesRegex(RuntimeError, "entry not ready"):
            self.navigate()
        self.hooks["restart_browser"].assert_not_called()

    def test_network_errors_are_not_misreported_as_timeouts(self):
        self.page.get.side_effect = RuntimeError("net::ERR_PROXY_CONNECTION_FAILED")

        with self.assertRaisesRegex(Exception, "ERR_PROXY_CONNECTION_FAILED"):
            self.navigate()
        self.assertFalse(any("加载超时" in line for line in self.logs))
        self.hooks["stop_browser"].assert_called_once()

    def test_cancel_during_navigation_does_not_restart_browser(self):
        class Cancelled(Exception):
            pass

        self.page.get.side_effect = BrowserNavigationTimeout("fixture")
        self.hooks["raise_if_cancelled"].side_effect = [None, Cancelled("stopped")]

        with self.assertRaises(Cancelled):
            self.navigate()
        self.hooks["restart_browser"].assert_not_called()
        self.hooks["click_email_signup_button"].assert_not_called()

    def test_cancel_after_document_load_does_not_continue(self):
        class Cancelled(Exception):
            pass

        self.hooks["raise_if_cancelled"].side_effect = [
            None,
            Cancelled("stopped"),
            Cancelled("stopped"),
        ]
        with self.assertRaises(Cancelled):
            self.navigate()
        self.hooks["restart_browser"].assert_not_called()
        self.hooks["click_email_signup_button"].assert_not_called()

    def test_cancel_during_retry_is_not_wrapped_as_navigation_failure(self):
        class Cancelled(Exception):
            pass

        self.page.get.side_effect = BrowserNavigationTimeout("fixture")
        self.hooks["raise_if_cancelled"].side_effect = [
            None,
            None,
            Cancelled("stopped"),
        ]
        with self.assertRaises(Cancelled):
            self.navigate()
        self.hooks["restart_browser"].assert_called_once()
        self.hooks["stop_browser"].assert_called_once()
        self.hooks["click_email_signup_button"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
