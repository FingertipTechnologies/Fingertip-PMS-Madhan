/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { AppsMenu } from "@web_responsive/components/apps_menu/apps_menu.esm";

// The footer shows at most this many quotes/posts; the rest are dropped
// (entries are already ordered by sequence, then date, server-side).
const MAX_FOOTER_POSTS = 4;

// Only true announcements go in the panel beside the app icons. Everything
// else — "Quote of the Day" and "Org-wide Update" (which is how the LinkedIn
// and YouTube entries are recorded) — is a post and belongs in the footer.
const ANNOUNCEMENT_KINDS = ["announcement"];

/**
 * Shared data and helpers for the two Homepage widgets. The announcements
 * panel sits beside the app icons and the posts row sits in the footer below
 * them, so they are two components rendered in two places over the same set
 * of records rather than one component owning both.
 */
class FtHomepageContent extends Component {
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({ items: [], loaded: false });

        onWillStart(async () => {
            try {
                const items = await this.orm.call(
                    "ft.quote.announcement",
                    "get_homepage_content",
                    []
                );
                this.state.items = Array.isArray(items) ? items : [];
            } catch (e) {
                // Never let these widgets break the Homepage for any user.
                console.warn("ft_homepage: could not load quote/announcement", e);
                this.state.items = [];
            }
            this.state.loaded = true;
        });
    }

    /** Entries for the announcements panel beside the app icons. */
    get announcements() {
        return this.state.items.filter((item) =>
            ANNOUNCEMENT_KINDS.includes(item.kind)
        );
    }

    /** Everything destined for the footer: not an announcement. */
    get footerItems() {
        return this.state.items.filter(
            (item) => !ANNOUNCEMENT_KINDS.includes(item.kind)
        );
    }

    /** Text entries — they scroll as a marquee across the top of the footer. */
    get quotes() {
        return this.footerItems.filter((item) => item.content_type === "text");
    }

    /** Image/video/social entries — the cards below the marquee, max 4. */
    get posts() {
        return this.footerItems
            .filter((item) => item.content_type !== "text")
            .slice(0, MAX_FOOTER_POSTS);
    }

    isYoutube(item) {
        const url = item.video_url;
        return !!url && (url.includes("youtube.com") || url.includes("youtu.be"));
    }

    youtubeEmbedUrl(item) {
        const url = item.video_url;
        let videoId = "";
        if (url.includes("youtu.be/")) {
            videoId = url.split("youtu.be/")[1];
        } else if (url.includes("v=")) {
            videoId = url.split("v=")[1];
        }
        videoId = videoId ? videoId.split("&")[0].split("?")[0] : "";
        // autoplay=1 starts the video immediately; browsers only allow
        // autoplay when muted (mute=1). loop needs the playlist param.
        return `https://www.youtube.com/embed/${videoId}?autoplay=1&mute=1&loop=1&playlist=${videoId}`;
    }
}

/** Quotes/posts row, rendered as the Homepage footer. */
export class FtQuoteWidget extends FtHomepageContent {
    static template = "ft_homepage.QuoteWidget";
}

/** Announcements panel, rendered to the right of the app icons grid. */
export class FtAnnouncementsPanel extends FtHomepageContent {
    static template = "ft_homepage.AnnouncementsPanel";
}

// Register both as child components of web_responsive's AppsMenu so they can
// be rendered inside its template (see quote_widget.xml).
patch(AppsMenu, {
    components: { ...AppsMenu.components, FtQuoteWidget, FtAnnouncementsPanel },
});
