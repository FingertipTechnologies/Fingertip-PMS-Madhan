/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { AppsMenu } from "@web_responsive/components/apps_menu/apps_menu.esm";

export class FtQuoteWidget extends Component {
    static template = "ft_homepage.QuoteWidget";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({ content: false, loaded: false });

        onWillStart(async () => {
            try {
                this.state.content = await this.orm.call(
                    "ft.quote.announcement",
                    "get_homepage_content",
                    []
                );
            } catch (e) {
                // Never let the quote widget break the Homepage for any user.
                console.warn("ft_homepage: could not load quote/announcement", e);
                this.state.content = false;
            }
            this.state.loaded = true;
        });
    }

    get isYoutube() {
        const url = this.state.content && this.state.content.video_url;
        return url && (url.includes("youtube.com") || url.includes("youtu.be"));
    }

    get youtubeEmbedUrl() {
        const url = this.state.content.video_url;
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

// Register the widget as a child component of web_responsive's AppsMenu so
// it can be rendered inside its template (see quote_widget.xml), right
// below the app icons grid.
patch(AppsMenu, {
    components: { ...AppsMenu.components, FtQuoteWidget },
});
