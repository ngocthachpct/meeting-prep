import { HttpService } from '@nestjs/axios';
import { ConfigService } from '@nestjs/config';
import { Test, TestingModule } from '@nestjs/testing';
import { of, throwError } from 'rxjs';
import { AxiosError } from 'axios';
import { MeetingService } from './meeting.service';

describe('MeetingService', () => {
  let service: MeetingService;
  let http: jest.Mocked<HttpService>;

  const mockHttpService = {
    post: jest.fn(),
  };

  const mockConfigService = {
    get: jest.fn((key: string) => {
      if (key === 'AGENT_SERVICE_URL') return 'http://test:8000';
      if (key === 'TRACKER_FILE_PATH') return ':memory:';
      return undefined;
    }),
  };

  beforeEach(async () => {
    jest.clearAllMocks();
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        MeetingService,
        { provide: HttpService, useValue: mockHttpService },
        { provide: ConfigService, useValue: mockConfigService },
      ],
    }).compile();

    service = module.get<MeetingService>(MeetingService);
    http = module.get(HttpService) as jest.Mocked<HttpService>;
  });

  describe('runPrep', () => {
    it('calls agent prep endpoint and returns data', async () => {
      const agentResponse = { mode: 'prep', markdown_brief: '# Brief' };
      mockHttpService.post.mockReturnValue(
        of({ data: agentResponse, status: 200, statusText: 'OK', headers: {}, config: {} } as any),
      );

      const result = await service.runPrep('user-1', 'evt_001');
      expect(result).toEqual(agentResponse);
      expect(mockHttpService.post).toHaveBeenCalledWith(
        'http://test:8000/meetings/prep',
        { user_id: 'user-1', meeting_id: 'evt_001' },
      );
    });
  });

  describe('runFollowup', () => {
    it('extracts and tracks valid action items', async () => {
      const agentResponse = {
        mode: 'followup',
        summary: 'Discussed sprint',
        action_items: [
          { owner: 'Alice', task: 'Finish API', deadline: 'Friday' },
          { owner: 'Bob', task: 'Write tests', deadline: 'Monday' },
        ],
      };
      mockHttpService.post.mockReturnValue(
        of({ data: agentResponse, status: 200, statusText: 'OK', headers: {}, config: {} } as any),
      );

      await service.runFollowup('user-1', 'transcript here');
      const tracker = service.getTracker();
      expect(tracker).toHaveLength(2);
      expect(tracker[0].owner).toBe('Alice');
      expect(tracker[0].task).toBe('Finish API');
      expect(tracker[0].deadline).toBe('Friday');
      expect(tracker[1].owner).toBe('Bob');
    });

    it('skips items with empty owner or task', async () => {
      const agentResponse = {
        mode: 'followup',
        action_items: [
          { owner: '', task: 'Something', deadline: '' },
          { owner: 'Charlie', task: '', deadline: '' },
          { owner: 'Dave', task: 'Valid task', deadline: 'Tomorrow' },
        ],
      };
      mockHttpService.post.mockReturnValue(
        of({ data: agentResponse, status: 200, statusText: 'OK', headers: {}, config: {} } as any),
      );

      await service.runFollowup('user-1', 'transcript');
      const tracker = service.getTracker();
      expect(tracker).toHaveLength(1);
      expect(tracker[0].owner).toBe('Dave');
    });

    it('handles missing action_items field gracefully', async () => {
      mockHttpService.post.mockReturnValue(
        of({ data: { mode: 'followup' }, status: 200, statusText: 'OK', headers: {}, config: {} } as any),
      );

      await expect(service.runFollowup('user-1', 'hello')).resolves.not.toThrow();
      expect(service.getTracker()).toHaveLength(0);
    });

    it('sets default deadline when not provided', async () => {
      mockHttpService.post.mockReturnValue(
        of({
          data: {
            mode: 'followup',
            action_items: [{ owner: 'Eve', task: 'Review PR' }],
          },
          status: 200,
          statusText: 'OK',
          headers: {},
          config: {},
        } as any),
      );

      await service.runFollowup('user-1', 'transcript');
      expect(service.getTracker()[0].deadline).toBe('not specified');
    });
  });

  describe('callAgent error handling', () => {
    it('throws InternalServerErrorException on HTTP error', async () => {
      const error = new AxiosError('Service Unavailable', '503', undefined, undefined, {
        data: 'Agent crashed',
        status: 503,
        statusText: 'Service Unavailable',
        headers: {},
        config: {} as any,
      });
      mockHttpService.post.mockReturnValue(throwError(() => error));

      await expect(service.runPrep('u1', 'evt_1')).rejects.toThrow('Agent service unavailable');
    });

    it('throws InternalServerErrorException on network error', async () => {
      const error = new AxiosError('connect ECONNREFUSED', 'ENOTFOUND');
      mockHttpService.post.mockReturnValue(throwError(() => error));

      await expect(service.runPrep('u1', 'evt_1')).rejects.toThrow('Agent service unavailable');
    });
  });

  describe('getTracker', () => {
    it('returns accumulated action items across multiple runs', async () => {
      mockHttpService.post.mockReturnValue(
        of({
          data: {
            mode: 'followup',
            action_items: [{ owner: 'X', task: 'Task 1', deadline: 'soon' }],
          },
          status: 200,
          statusText: 'OK',
          headers: {},
          config: {},
        } as any),
      );

      await service.runFollowup('u1', 't1');
      await service.runFollowup('u1', 't2');

      expect(service.getTracker()).toHaveLength(2);
    });
  });
});
