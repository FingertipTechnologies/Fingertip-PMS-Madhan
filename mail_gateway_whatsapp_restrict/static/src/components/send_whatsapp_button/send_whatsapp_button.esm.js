import {SendWhatsappButton} from "@mail_gateway_whatsapp/components/send_whatsapp_button/send_whatsapp_button.esm";
import {patch} from "@web/core/utils/patch";
import {user} from "@web/core/user";
import {onWillStart, useState} from "@odoo/owl";

const ALLOWED_GROUPS = [
    "sales_team.group_sale_salesman",
    "mass_mailing.group_mass_mailing_user",
];

patch(SendWhatsappButton.prototype, {
    setup() {
        super.setup();
        this.whatsappAccess = useState({canSend: false});
        onWillStart(async () => {
            for (const g of ALLOWED_GROUPS) {
                if (await user.hasGroup(g)) {
                    this.whatsappAccess.canSend = true;
                    return;
                }
            }
        });
    },
    get canSendWhatsapp() {
        return this.whatsappAccess.canSend;
    },
});
