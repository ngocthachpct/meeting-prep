import { Injectable, InternalServerErrorException, Logger, OnModuleInit } from '@nestjs/common';
import { HttpService } from '@nestjs/axios';
import { ConfigService } from '@nestjs/config';
import { AxiosError } from 'axios';
import { firstValueFrom } from 'rxjs';
import * as fs from 'fs/promises';
import * as path from 'path';

interface RawActionItem {
  owner?: unknown;
  task?: unknown;
  deadline?: unknown;
}

export interface ActionItem {
  owner: string;
  task: string;
  deadline: string;
  meetingRunAt: string;
}

export interface AgentFollowupResponse {
  mode?: string;
  action_items?: RawActionItem[];
  [key: string]: unknown;
}

@Injectable()
export class MeetingService implements OnModuleInit {
  private readonly logger = new Logger(MeetingService.name);
  private readonly agentServiceUrl: string;
  private readonly trackerPath: string;

  private actionItemTracker: ActionItem[] = [];

  constructor(
    private readonly http: HttpService,
    private readonly config: ConfigService,
  ) {
    this.agentServiceUrl =
      this.config.get<string>('AGENT_SERVICE_URL') ?? 'http://localhost:8000';
    this.trackerPath =
      this.config.get<string>('TRACKER_FILE_PATH') ?? path.join(process.cwd(), 'data', 'tracker.json');
  }

  async onModuleInit() {
    try {
      const raw = await fs.readFile(this.trackerPath, 'utf-8');
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        this.actionItemTracker = parsed;
        this.logger.log(`Loaded ${parsed.length} action item(s) from ${this.trackerPath}`);
      }
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
        this.logger.log('No existing tracker file found, starting fresh');
      } else {
        this.logger.warn(`Could not load tracker file: ${(err as Error).message}, starting fresh`);
      }
    }
  }

  private async saveTracker() {
    try {
      await fs.mkdir(path.dirname(this.trackerPath), { recursive: true });
      await fs.writeFile(this.trackerPath, JSON.stringify(this.actionItemTracker, null, 2), 'utf-8');
    } catch (err) {
      this.logger.error(`Failed to save tracker: ${(err as Error).message}`);
    }
  }

  private async callAgent<T>(url: string, body: Record<string, unknown>): Promise<T> {
    try {
      const { data } = await firstValueFrom(this.http.post<T>(url, body));
      return data;
    } catch (err) {
      if (err instanceof AxiosError) {
        const status = err.response?.status ?? 503;
        const msg = err.response?.data
          ? JSON.stringify(err.response.data)
          : err.message;
        this.logger.error(`Agent service error (${status}): ${msg}`);
        throw new InternalServerErrorException(
          `Agent service unavailable: ${msg}`,
        );
      }
      this.logger.error(`Unexpected error calling agent: ${(err as Error).message}`);
      throw new InternalServerErrorException('Failed to call agent service');
    }
  }

  async runPrep(userId: string, meetingId: string) {
    return this.callAgent(`${this.agentServiceUrl}/meetings/prep`, {
      user_id: userId,
      meeting_id: meetingId,
    });
  }

  async runFollowup(userId: string, transcript: string) {
    const data = await this.callAgent<AgentFollowupResponse>(
      `${this.agentServiceUrl}/meetings/followup`,
      { user_id: userId, transcript },
    );

    if (Array.isArray(data.action_items)) {
      const runAt = new Date().toISOString();
      const validItems: ActionItem[] = [];
      let skipped = 0;
      for (const item of data.action_items) {
        const owner = String(item?.owner ?? '').trim();
        const task = String(item?.task ?? '').trim();
        if (!owner || !task) {
          skipped++;
          this.logger.warn(`Skipped invalid action item (missing owner or task): ${JSON.stringify(item)}`);
          continue;
        }
        validItems.push({ owner, task, deadline: String(item?.deadline ?? 'not specified'), meetingRunAt: runAt });
      }
      if (validItems.length > 0) {
        this.actionItemTracker.push(...validItems);
        await this.saveTracker();
        this.logger.log(`Tracked ${validItems.length} new action item(s)`);
      }
      if (skipped > 0) {
        this.logger.warn(`Skipped ${skipped} invalid action item(s) from agent output`);
      }
    }

    return data;
  }

  getTracker() {
    return this.actionItemTracker;
  }
}
