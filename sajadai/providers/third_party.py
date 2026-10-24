"""Analytics tools without a public API a single creator can use today (checked against each vendor's own
docs, 2026-10; details in docs/PROVIDERS.md). They're listed so the page is complete and honest."""

SOON = [
    ("later", "Later", "زمان‌بندی و آنالیتیکس Later.", "paid", "analytics", ("schedule",),
     "Later API عمومی برای خوندن آمار نداره.", "https://help.later.com/"),
    ("hootsuite", "Hootsuite", "زمان‌بندی Hootsuite.", "paid", "analytics", ("schedule", "publish"),
     "API هوت‌سوئیت برای انتشار و پیامه و آمار اینستاگرام رو نمی‌ده.", "https://developer.hootsuite.com/"),
    ("sprout", "Sprout Social", "آنالیتیکس Sprout Social.", "paid", "analytics", ("followers_daily", "views", "likes", "comments", "saves", "shares"),
     "API فقط تو پلن Advanced (حدود ۳۹۹ دلار برای هر نفر در ماه) هست.", "https://api.sproutsocial.com/docs/"),
    ("iconosquare", "Iconosquare", "آنالیتیکس Iconosquare.", "paid", "analytics", ("followers_daily", "views", "reel_reach", "likes", "comments", "saves"),
     "API فقط برای پلن‌های سازمانیه (و MCP آزمایشی).", "https://www.iconosquare.com/"),
    ("agorapulse", "Agorapulse", "آنالیتیکس Agorapulse.", "paid", "analytics", ("followers_daily", "views", "likes", "comments"),
     "Analytics Open API فقط تو پلن Custom هست.", "https://www.agorapulse.com/"),
    ("socialinsider", "Socialinsider", "آنالیتیکس و بنچمارک رقبا.", "paid", "analytics", ("followers_daily", "views", "likes", "comments", "competitors"),
     "API از طریق تیم فروش و قرارداد سازمانی داده می‌شه.", "https://www.socialinsider.io/"),
]
