import unittest
from unittest.mock import patch

from eitaa_source import clean_channel, parse_page, safe_media_url


class EitaaSourceTests(unittest.TestCase):
    def test_channel_forms(self):
        self.assertEqual(clean_channel("@news_channel"), "news_channel")
        self.assertEqual(clean_channel("https://eitaa.com/news_channel"), "news_channel")
        self.assertEqual(clean_channel("https://eitaa.com/s/news_channel"), "news_channel")

    def test_reject_untrusted_urls(self):
        for link in ("https://evil.example/news_channel",
                     "https://eitaa.com.evil.example/news_channel",
                     "https://eitaa.com@evil.example/news_channel"):
            with self.assertRaises(ValueError):
                clean_channel(link)

    def test_media_origin(self):
        self.assertIsNone(safe_media_url("http://127.0.0.1/private"))
        self.assertIsNone(safe_media_url("https://example.com/image.jpg"))
        self.assertEqual(safe_media_url("/media/hello.jpg"), "https://eitaa.com/media/hello.jpg")

    def test_parse_public_channel(self):
        html = """
        <div class="etme_widget_message" data-post="example_news/42">
          <div class="etme_widget_message_text">سلام #آزمایش
            <a href="https://example.org/story">نشانی</a>
          </div>
          <a class="etme_widget_message_photo_wrap"
             style="background-image:url('/media/photo.jpg')"></a>
          <time datetime="2026-10-10T08:00:00+00:00"></time>
        </div>
        """
        title, posts = parse_page(html, "example_news")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["external_id"], "42")
        self.assertIn("#آزمایش", posts[0]["raw_text"])
        self.assertEqual(posts[0]["media"][0]["kind"], "photo")
        self.assertEqual(posts[0]["metadata"]["links"], ["https://example.org/story"])


if __name__ == "__main__":
    unittest.main()
