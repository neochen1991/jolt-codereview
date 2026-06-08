import type { AgentRepository } from "../repositories/AgentRepository.js";

export class AgentConfigService {
  constructor(private readonly agentRepository: AgentRepository) {}

  listAgents(projectId: string) {
    return this.agentRepository.listWithProfiles(projectId);
  }

  listExpertProfiles(projectId: string) {
    return this.agentRepository.listExpertProfiles(projectId);
  }

  findExpertProfile(projectId: string, agentKey: string) {
    return this.agentRepository.findExpertProfile(projectId, agentKey);
  }

  findAgent(projectId: string, agentId: string) {
    return this.agentRepository.findByProjectAndAgent(projectId, agentId);
  }

  createCustomAgent(input: Parameters<AgentRepository["createCustomAgent"]>[0]) {
    return this.agentRepository.createCustomAgent(input);
  }

  updateAgent(projectId: string, agentId: string, input: Record<string, unknown>) {
    return this.agentRepository.update(projectId, agentId, input);
  }

  updateExpertProfile(projectId: string, agentKey: string, input: Record<string, unknown>) {
    return this.agentRepository.updateExpertProfile(projectId, agentKey, input);
  }
}
