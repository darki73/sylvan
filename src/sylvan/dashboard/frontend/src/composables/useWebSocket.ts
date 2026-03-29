import { ref } from "vue";
import { WebSocketClient } from "@/services";
import type { PushHandler } from "@/interfaces";

const connected = ref(false);

function buildWsUrl(): string {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/ws/dashboard`;
}

let client: WebSocketClient | null = null;

function getClient(): WebSocketClient {
    if (!client) {
        client = new WebSocketClient(buildWsUrl());
        client.setConnectionCallback((state) => {
            connected.value = state;
        });
        client.connect();
    }
    return client;
}

export function useWebSocket() {
    const ws = getClient();

    return {
        connected,
        request: ws.request.bind(ws) as typeof ws.request,
        on: ws.on.bind(ws) as (type: string, handler: PushHandler) => void,
        off: ws.off.bind(ws) as (type: string, handler: PushHandler) => void,
    };
}
