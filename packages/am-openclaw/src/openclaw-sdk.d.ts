declare module "openclaw/plugin-sdk/core" {
  export type OpenClawPluginApi = {
    pluginConfig: Record<string, unknown>;
    logger?: {
      debug?: (...args: unknown[]) => void;
      info?: (...args: unknown[]) => void;
      warn?: (...args: unknown[]) => void;
      error?: (...args: unknown[]) => void;
    };
    registerMemoryPromptSection(builder: (params: {
      availableTools: Set<string>;
      citationsMode?: string;
    }) => string[]): void;
    registerMemoryRuntime(runtime: unknown): void;
    registerContextEngine(id: string, factory: () => unknown | Promise<unknown>): void;
  };

  export function definePluginEntry(options: {
    id: string;
    name: string;
    description: string;
    kind?: "memory" | "context-engine";
    configSchema?: Record<string, unknown>;
    register(api: OpenClawPluginApi): void;
  }): unknown;
}

declare module "openclaw/plugin-sdk" {
  export type AgentMessage = {
    role?: string;
    content?: unknown;
  };

  export type AssembleResult = {
    messages: AgentMessage[];
    estimatedTokens: number;
    systemPromptAddition?: string;
  };

  export type CompactResult = {
    ok: boolean;
    compacted: boolean;
    reason?: string;
    result?: {
      summary?: string;
      tokensBefore: number;
      tokensAfter?: number;
      details?: unknown;
    };
  };

  export type BootstrapResult = {
    bootstrapped: boolean;
    importedMessages?: number;
    reason?: string;
  };

  export type IngestResult = {
    ingested: boolean;
  };

  export type IngestBatchResult = {
    ingestedCount: number;
  };

  export interface ContextEngine {
    readonly info: {
      id: string;
      name: string;
      version?: string;
      ownsCompaction?: boolean;
    };
    bootstrap?(params: {
      sessionId: string;
      sessionKey?: string;
      sessionFile: string;
    }): Promise<BootstrapResult>;
    ingest(params: {
      sessionId: string;
      sessionKey?: string;
      message: AgentMessage;
      isHeartbeat?: boolean;
    }): Promise<IngestResult>;
    ingestBatch?(params: {
      sessionId: string;
      sessionKey?: string;
      messages: AgentMessage[];
      isHeartbeat?: boolean;
    }): Promise<IngestBatchResult>;
    afterTurn?(params: {
      sessionId: string;
      sessionKey?: string;
      sessionFile: string;
      messages: AgentMessage[];
      prePromptMessageCount: number;
      autoCompactionSummary?: string;
      isHeartbeat?: boolean;
      tokenBudget?: number;
      runtimeContext?: Record<string, unknown>;
    }): Promise<void>;
    assemble(params: {
      sessionId: string;
      sessionKey?: string;
      messages: AgentMessage[];
      tokenBudget?: number;
      model?: string;
      prompt?: string;
    }): Promise<AssembleResult>;
    compact(params: {
      sessionId: string;
      sessionKey?: string;
      sessionFile: string;
      tokenBudget?: number;
      force?: boolean;
      currentTokenCount?: number;
      compactionTarget?: "budget" | "threshold";
      customInstructions?: string;
      runtimeContext?: Record<string, unknown>;
    }): Promise<CompactResult>;
    dispose?(): Promise<void>;
  }
}
