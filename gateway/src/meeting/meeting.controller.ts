import { Body, Controller, Get, Post, UseGuards } from '@nestjs/common';
import { ApiKeyGuard } from '../auth/api-key.guard';
import { CurrentUser } from '../auth/user.decorator';
import { MeetingService } from './meeting.service';

@Controller('meetings')
@UseGuards(ApiKeyGuard)
export class MeetingController {
  constructor(private readonly meetingService: MeetingService) {}

  @Post('prep')
  runPrep(@CurrentUser() userId: string, @Body() body: { meetingId: string }) {
    return this.meetingService.runPrep(userId, body.meetingId);
  }

  @Post('followup')
  runFollowup(@CurrentUser() userId: string, @Body() body: { transcript: string }) {
    return this.meetingService.runFollowup(userId, body.transcript);
  }

  @Get('tracker')
  getTracker(@CurrentUser() userId: string) {
    return this.meetingService.getTracker();
  }
}
