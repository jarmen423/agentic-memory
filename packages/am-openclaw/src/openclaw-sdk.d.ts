declare module "openclaw/plugin-sdk/core" {
  export type OpenClawMemoryRuntime = {
    getMemorySearchManager(params: {
      cfg: unknown;
      agentId: string;
      purpose?: "default" | "status";
    }): Promise<{
      manager: unknown;
      error?: string;
    }>;
    resolveMemoryBackendConfig(params?: unknown): unknown;
    closeAllMemorySearchManagers?(): Promise<void>;
  };

  export type OpenClawMemoryCapability = {
    runtime?: OpenClawMemoryRuntime;
    promptBuilder?: (params: {
      availableTools: Set<string>;
      citationsMode?: string;
    }) => string[];
    publicArtifacts?: {
      listArtifacts?(params: { cfg: unknown }): Promise<unknown[]>;
    };
  };

  export type OpenClawPluginApi = {
    pluginConfig: Record<string, unknown>;
    registrationMode?: "full" | "cli-metadata";
    logger?: {
      debug?: (...args: unknown[]) => void;
      info?: (...args: unknown[]) => void;
      warn?: (...args: unknown[]) => void;
      error?: (...args: unknown[]) => void;
    };
    registerCli?(
      registrar: (params: {
        program: unknown;
        config: Record<string, unknown>;
        workspaceDir?: string;
        logger?: OpenClawPluginApi["logger"];
      }) => void,
      opts?: {
        descriptors?: Array<{
          name: string;
          description: string;
          hasSubcommands?: boolean;
        }>;
      },
    ): void;
    registerMemoryCapability?(capability: OpenClawMemoryCapability): void;
    registerMemoryPromptSection(builder: (params: {
      availableTools: Set<string>;
      citationsMode?: string;
    }) => string[]): void;
    registerMemoryRuntime(runtime: OpenClawMemoryRuntime): void;
    registerContextEngine(id: string, factory: () => unknown | Promise<unknown>): void;
  };

  export function definePluginEntry(options: {
    id: string;
    name: string;
    description: string;
    kind?: "memory" | "context-engine" | Array<"memory" | "context-engine">;
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

declare module "openclaw/plugin-sdk/config-runtime" {
  export function updateConfig(
    mutate: (config: Record<string, unknown>) => Record<string, unknown>,
  ): Promise<void>;
}
