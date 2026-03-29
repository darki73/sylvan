import type { DashboardRequest, DashboardResponse, PushHandler } from "@/interfaces";

let idCounter = 0;
function nextId(): string {
    return `req-${++idCounter}-${Date.now().toString(36)}`;
}

export class WebSocketClient {
    private ws: WebSocket | null = null;
    private pushListeners = new Map<string, Set<PushHandler>>();
    private pendingRequests = new Map<string, {
        resolve: (data: unknown) => void;
        reject: (err: Error) => void;
    }>();
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private connectWaiters: Array<() => void> = [];
    private _connected = false;
    private onConnectionChange: ((connected: boolean) => void) | null = null;

    constructor(private url: string) {}

    get connected(): boolean {
        return this._connected;
    }

    setConnectionCallback(cb: (connected: boolean) => void): void {
        this.onConnectionChange = cb;
    }

    connect(): void {
        if (this.ws?.readyState === WebSocket.OPEN) return;

        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
            this._connected = true;
            this.onConnectionChange?.(true);
            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
                this.reconnectTimer = null;
            }
            for (const waiter of this.connectWaiters) waiter();
            this.connectWaiters = [];
        };

        this.ws.onmessage = (event: MessageEvent) => {
            const msg: DashboardResponse = JSON.parse(event.data);
            if (msg.id && this.pendingRequests.has(msg.id)) {
                const pending = this.pendingRequests.get(msg.id)!;
                this.pendingRequests.delete(msg.id);
                if (msg.error) {
                    pending.reject(new Error(msg.error));
                } else {
                    pending.resolve(msg.data);
                }
            } else {
                const handlers = this.pushListeners.get(msg.type);
                if (handlers) {
                    handlers.forEach((fn) => fn(msg.data));
                }
            }
        };

        this.ws.onclose = () => {
            this._connected = false;
            this.onConnectionChange?.(false);
            this.ws = null;
            for (const [, pending] of this.pendingRequests) {
                pending.reject(new Error("Connection lost"));
            }
            this.pendingRequests.clear();
            this.reconnectTimer = setTimeout(() => this.connect(), 2000);
        };

        this.ws.onerror = () => {
            this.ws?.close();
        };
    }

    disconnect(): void {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        this.ws?.close();
        this.ws = null;
    }

    private waitForConnection(): Promise<void> {
        if (this.ws?.readyState === WebSocket.OPEN) {
            return Promise.resolve();
        }
        return new Promise((resolve) => {
            this.connectWaiters.push(resolve);
        });
    }

    async request<T = unknown>(type: string, args?: Record<string, unknown>): Promise<T> {
        await this.waitForConnection();
        return new Promise((resolve, reject) => {
            const id = nextId();
            this.pendingRequests.set(id, {
                resolve: resolve as (data: unknown) => void,
                reject,
            });
            const msg: DashboardRequest = { id, type, args };
            this.ws!.send(JSON.stringify(msg));
        });
    }

    on(type: string, handler: PushHandler): void {
        if (!this.pushListeners.has(type)) {
            this.pushListeners.set(type, new Set());
        }
        this.pushListeners.get(type)!.add(handler);
    }

    off(type: string, handler: PushHandler): void {
        this.pushListeners.get(type)?.delete(handler);
    }
}
