// Copyright 2025 Google LLC

// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at

//     https://www.apache.org/licenses/LICENSE-2.0

// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { Component, input } from '@angular/core';
import { WorkflowData } from '../workflow-data/workflow-data';
import { CommonModule } from '@angular/common';

import { TruncatePipe } from '../app/truncate.pipe';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatGridListModule } from '@angular/material/grid-list';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
@Component({
  selector: 'app-workflow-entry',
  imports: [
    CommonModule,
    MatExpansionModule,
    MatGridListModule,
    MatIconModule,
    MatTooltipModule,
    TruncatePipe
  ],
  templateUrl: './workflow-entry.component.html',
  styleUrl: './workflow-entry.component.scss'
})
export class WorkflowEntryComponent {
  workData = input.required<WorkflowData>();

}
