export interface WebSocketMessage {
  type: string;
  data?: Record<string, unknown>;
}

export type MessageHandler = (data: unknown) => void;

export interface WebSocketService {
  readonly connected: boolean;
  subscribe(type: string, handler: MessageHandler): void;
  unsubscribe(type: string, handler: MessageHandler): void;
  send(msg: WebSocketMessage): void;
}
