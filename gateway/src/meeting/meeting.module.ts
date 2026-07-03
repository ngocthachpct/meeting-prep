import { Module } from '@nestjs/common';
import { HttpModule } from '@nestjs/axios';
import { ApiKeyGuard } from '../auth/api-key.guard';
import { MeetingController } from './meeting.controller';
import { MeetingService } from './meeting.service';

@Module({
  imports: [HttpModule],
  controllers: [MeetingController],
  providers: [MeetingService, ApiKeyGuard],
})
export class MeetingModule {}
