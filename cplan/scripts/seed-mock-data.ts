/**
 * Seed Script: Populate Microsoft Lists with Enterprise Mock Data
 *
 * Run this after setting up your Microsoft Lists to create realistic test data
 *
 * Usage:
 *   npm run seed-data
 */

import { communicationsService, templatesService, packsService } from '../src/lib/microsoft-lists-paginated';

// Realistic enterprise communication types
const COMMUNICATION_TYPES = {
  QUARTERLY_RESULTS: {
    type: 'ANNOUNCEMENT' as const,
    priority: 'HIGH' as const,
    titles: [
      'Q1 2025 Financial Results Announced',
      'Q2 2025 Earnings Beat Expectations',
      'Q3 2025 Quarterly Performance Update',
      'Q4 2025 Year-End Financial Summary',
      'Strong Q1 2024 Results Drive Growth',
      'Q2 2024 Revenue Surpasses Targets',
    ],
    channels: ['EMAIL', 'INTRANET', 'TEAMS'],
  },
  POLICY_UPDATES: {
    type: 'POLICY' as const,
    priority: 'MEDIUM' as const,
    titles: [
      'Updated Remote Work Policy - Effective March 2025',
      'New Expense Reimbursement Guidelines',
      'IT Security Policy Amendment',
      'Travel Policy Updates for 2025',
      'Data Privacy Policy Revision',
      'Updated Code of Conduct',
    ],
    channels: ['EMAIL', 'INTRANET'],
  },
  LEADERSHIP_MESSAGES: {
    type: 'ANNOUNCEMENT' as const,
    priority: 'HIGH' as const,
    titles: [
      'CEO Message: Strategic Vision for 2025',
      'Leadership Update: Organizational Changes',
      'Welcome Message from New CFO',
      'Town Hall Recap: Executive Q&A',
      'Board of Directors Update',
      'Annual Leadership Letter to Employees',
    ],
    channels: ['EMAIL', 'INTRANET', 'TEAMS', 'DIGITAL_SIGNAGE'],
  },
  EVENTS: {
    type: 'EVENT' as const,
    priority: 'MEDIUM' as const,
    titles: [
      'Annual Company Conference - Save the Date',
      'Virtual Town Hall: February 15th',
      'Department Offsite Meeting Agenda',
      'Customer Appreciation Event Invitation',
      'Team Building Workshop Registration',
      'Diversity & Inclusion Summit 2025',
    ],
    channels: ['EMAIL', 'TEAMS', 'INTRANET'],
  },
  NEWSLETTERS: {
    type: 'NEWSLETTER' as const,
    priority: 'LOW' as const,
    titles: [
      'Monthly Digest: January 2025',
      'Employee Spotlight Newsletter',
      'Innovation Update: Latest Projects',
      'Global News Roundup',
      'HR Newsletter: Benefits & Wellness',
      'IT Updates & Technology News',
    ],
    channels: ['EMAIL', 'INTRANET'],
  },
  URGENT_ALERTS: {
    type: 'ALERT' as const,
    priority: 'URGENT' as const,
    titles: [
      'System Maintenance Tonight: 11 PM - 2 AM',
      'Weather Alert: Office Closure Notice',
      'Security Incident Notification',
      'Critical Software Update Required',
      'Emergency Contact Information Update',
      'Building Evacuation Drill - Tomorrow',
    ],
    channels: ['EMAIL', 'SMS', 'TEAMS', 'MOBILE_APP'],
  },
  TRAINING: {
    type: 'UPDATE' as const,
    priority: 'MEDIUM' as const,
    titles: [
      'Mandatory Compliance Training Due March 31',
      'New Hire Orientation Schedule',
      'Leadership Development Program Enrollment',
      'Technical Skills Workshop Series',
      'Cybersecurity Awareness Training',
      'Diversity Training Registration Open',
    ],
    channels: ['EMAIL', 'INTRANET', 'TEAMS'],
  },
  BENEFITS: {
    type: 'UPDATE' as const,
    priority: 'MEDIUM' as const,
    titles: [
      'Open Enrollment: Health Benefits 2025',
      'New Wellness Program Launched',
      '401k Match Increase Announcement',
      'Employee Assistance Program Update',
      'Parental Leave Policy Enhancement',
      'Mental Health Resources Available',
    ],
    channels: ['EMAIL', 'INTRANET'],
  },
};

// Communication statuses with realistic distribution
const STATUS_DISTRIBUTION = [
  { status: 'PUBLISHED', weight: 50 },
  { status: 'SCHEDULED', weight: 15 },
  { status: 'DRAFT', weight: 20 },
  { status: 'REVIEW', weight: 10 },
  { status: 'ARCHIVED', weight: 5 },
];

// Generate realistic content based on type
function generateContent(title: string, type: string): string {
  const contentTemplates: Record<string, string[]> = {
    ANNOUNCEMENT: [
      `Dear Team,\n\nWe are pleased to announce: ${title}.\n\nThis represents a significant milestone for our organization. Key highlights include:\n\n• Strong performance across all divisions\n• Continued investment in innovation\n• Enhanced employee programs\n\nThank you for your dedication and hard work.\n\nBest regards,\nLeadership Team`,
      `All Employees,\n\n${title}\n\nWe want to share this important update with our entire organization. Your contributions have been instrumental in achieving these results.\n\nFor detailed information, please visit the company intranet.\n\nRegards,\nExecutive Team`,
    ],
    POLICY: [
      `Dear Colleagues,\n\n${title}\n\nEffective immediately, the following policy changes will be implemented:\n\n1. Updated guidelines and procedures\n2. New compliance requirements\n3. Implementation timeline\n\nPlease review the full policy document on the HR portal. Direct questions to hr@company.com.\n\nThank you for your cooperation.\n\nHuman Resources`,
      `Team Members,\n\nPlease note: ${title}\n\nThis policy update aims to improve processes and ensure compliance with regulatory requirements. Key changes include enhanced flexibility and clearer guidelines.\n\nFull details available on the policy center.\n\nHR Department`,
    ],
    NEWSLETTER: [
      `${title}\n\nIn This Issue:\n• Company News & Updates\n• Employee Achievements\n• Upcoming Events\n• Department Highlights\n• Community Involvement\n\nRead the full newsletter for inspiring stories and important announcements from across our organization.\n\nStay connected!`,
      `Welcome to ${title}!\n\nThis month's highlights:\n\n✨ Employee Spotlight\n📅 Upcoming Events\n🎯 Strategic Initiatives\n🌟 Team Achievements\n\nDive in to learn more about what's happening across our company.\n\nCommunications Team`,
    ],
    EVENT: [
      `${title}\n\nDate: TBD\nTime: TBD\nLocation: Corporate Headquarters / Virtual\n\nAgenda:\n• Opening remarks\n• Strategic updates\n• Q&A session\n• Networking\n\nRegistration opens soon. Save the date!\n\nEvent Planning Team`,
      `You're Invited: ${title}\n\nJoin us for an engaging event featuring:\n- Keynote speakers\n- Interactive sessions\n- Team activities\n\nMore details and registration information to follow.\n\nLooking forward to seeing you there!`,
    ],
    ALERT: [
      `⚠️ IMPORTANT NOTICE: ${title}\n\nImmediate Action Required:\n\nWhat: [Alert details]\nWhen: [Timeline]\nAction Needed: [Steps to take]\n\nPlease acknowledge receipt of this message.\n\nIT/Security Team`,
      `🔔 ALERT: ${title}\n\nThis is a time-sensitive notification requiring your attention.\n\nPlease review the information below and take necessary action:\n\n[Details]\n\nContact the help desk with questions: support@company.com\n\nThank you for your prompt attention.`,
    ],
    UPDATE: [
      `${title}\n\nWe want to inform you about important updates:\n\n• What's changing\n• When it takes effect\n• What you need to do\n\nAdditional resources and FAQs are available on the company portal.\n\nThank you,\nManagement`,
      `Team Update: ${title}\n\nHere's what you need to know:\n\n✓ Background and context\n✓ Changes and improvements\n✓ Next steps\n\nQuestions? Contact your manager or department lead.\n\nBest regards`,
    ],
  };

  const templates = contentTemplates[type] || contentTemplates['UPDATE'];
  return templates[Math.floor(Math.random() * templates.length)];
}

// Generate random date in the past 6 months
function randomPastDate(): Date {
  const now = new Date();
  const sixMonthsAgo = new Date(now.getTime() - 180 * 24 * 60 * 60 * 1000);
  const randomTime = sixMonthsAgo.getTime() + Math.random() * (now.getTime() - sixMonthsAgo.getTime());
  return new Date(randomTime);
}

// Generate future date for scheduled items
function randomFutureDate(): Date {
  const now = new Date();
  const threeMonthsFromNow = new Date(now.getTime() + 90 * 24 * 60 * 60 * 1000);
  const randomTime = now.getTime() + Math.random() * (threeMonthsFromNow.getTime() - now.getTime());
  return new Date(randomTime);
}

// Weighted random status selection
function getRandomStatus(): string {
  const totalWeight = STATUS_DISTRIBUTION.reduce((sum, item) => sum + item.weight, 0);
  let random = Math.random() * totalWeight;

  for (const item of STATUS_DISTRIBUTION) {
    random -= item.weight;
    if (random <= 0) return item.status;
  }

  return 'DRAFT';
}

// Sample users
const MOCK_USERS = [
  { id: 'user-001', name: 'Sarah Johnson', email: 'sarah.johnson@company.com', dept: 'Communications' },
  { id: 'user-002', name: 'Michael Chen', email: 'michael.chen@company.com', dept: 'HR' },
  { id: 'user-003', name: 'Jennifer Martinez', email: 'jennifer.martinez@company.com', dept: 'IT' },
  { id: 'user-004', name: 'David Thompson', email: 'david.thompson@company.com', dept: 'Finance' },
  { id: 'user-005', name: 'Emily Rodriguez', email: 'emily.rodriguez@company.com', dept: 'Leadership' },
  { id: 'user-006', name: 'James Wilson', email: 'james.wilson@company.com', dept: 'Operations' },
  { id: 'user-007', name: 'Lisa Anderson', email: 'lisa.anderson@company.com', dept: 'Marketing' },
];

// Tags
const TAGS = [
  'Urgent', 'Company-Wide', 'Q1 2025', 'Q4 2024', 'Finance', 'HR', 'IT',
  'Leadership', 'Training', 'Policy', 'Benefits', 'Security', 'Global',
  'Department', 'Mandatory', 'Optional', 'Deadline', 'Action Required'
];

// Main seed function
async function seedMockData() {
  console.log('🌱 Starting to seed mock data...\n');

  const allCommunications = [];
  let count = 0;

  // Generate communications for each category
  for (const [category, config] of Object.entries(COMMUNICATION_TYPES)) {
    console.log(`📝 Creating ${category} communications...`);

    for (const title of config.titles) {
      const status = getRandomStatus();
      const user = MOCK_USERS[Math.floor(Math.random() * MOCK_USERS.length)];
      const numTags = Math.floor(Math.random() * 4) + 1;
      const selectedTags = [];

      for (let i = 0; i < numTags; i++) {
        const tag = TAGS[Math.floor(Math.random() * TAGS.length)];
        if (!selectedTags.includes(tag)) selectedTags.push(tag);
      }

      const publishDate = status === 'PUBLISHED' || status === 'ARCHIVED'
        ? randomPastDate()
        : status === 'SCHEDULED'
        ? randomFutureDate()
        : null;

      const communication = {
        title,
        description: `${category.replace(/_/g, ' ')} - ${title.substring(0, 100)}`,
        content: generateContent(title, config.type),
        type: config.type,
        priority: config.priority,
        status,
        publishDate: publishDate?.toISOString(),
        expiryDate: publishDate ? new Date(publishDate.getTime() + 90 * 24 * 60 * 60 * 1000).toISOString() : null,
        ownerId: user.id,
        ownerEmail: user.email,
        ownerName: user.name,
        channels: config.channels,
        tags: selectedTags,
        metadata: {
          department: user.dept,
          category,
          createdBy: user.name,
        },
      };

      allCommunications.push(communication);
      count++;
    }
  }

  console.log(`\n✅ Generated ${count} communications`);
  console.log('\n📤 Uploading to Microsoft Lists...\n');

  // Upload in batches to avoid overwhelming the API
  const BATCH_SIZE = 5;
  let uploaded = 0;
  let errors = 0;

  for (let i = 0; i < allCommunications.length; i += BATCH_SIZE) {
    const batch = allCommunications.slice(i, i + BATCH_SIZE);

    await Promise.all(
      batch.map(async (comm) => {
        try {
          await communicationsService.create(comm);
          uploaded++;
          console.log(`✓ [${uploaded}/${count}] Created: ${comm.title.substring(0, 60)}...`);
        } catch (error) {
          errors++;
          console.error(`✗ Failed to create: ${comm.title}`);
          console.error(`  Error: ${(error as Error).message}`);
        }
      })
    );

    // Small delay between batches
    if (i + BATCH_SIZE < allCommunications.length) {
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }

  console.log('\n' + '='.repeat(80));
  console.log('📊 SEED SUMMARY');
  console.log('='.repeat(80));
  console.log(`✅ Successfully uploaded: ${uploaded} communications`);
  console.log(`❌ Failed uploads: ${errors} communications`);
  console.log(`📈 Success rate: ${((uploaded / count) * 100).toFixed(1)}%`);
  console.log('='.repeat(80));

  // Create some templates
  console.log('\n📋 Creating templates...');
  const templates = [
    {
      name: 'Quarterly Results Template',
      description: 'Standard template for quarterly financial results',
      content: 'Dear Team,\n\nWe are pleased to announce our [QUARTER] [YEAR] financial results...\n\n[DETAILS]\n\nBest regards,\nLeadership Team',
      type: 'ANNOUNCEMENT',
      category: 'Financial',
      variables: { QUARTER: 'text', YEAR: 'text', DETAILS: 'richtext' },
    },
    {
      name: 'Policy Update Template',
      description: 'Template for policy announcements',
      content: 'Dear Colleagues,\n\n[POLICY_NAME]\n\nEffective [DATE], the following changes...\n\nHuman Resources',
      type: 'POLICY',
      category: 'HR',
      variables: { POLICY_NAME: 'text', DATE: 'date' },
    },
    {
      name: 'Event Invitation Template',
      description: 'Template for event announcements',
      content: 'You\'re Invited: [EVENT_NAME]\n\nDate: [DATE]\nTime: [TIME]\nLocation: [LOCATION]\n\nRegister now!',
      type: 'EVENT',
      category: 'Events',
      variables: { EVENT_NAME: 'text', DATE: 'date', TIME: 'text', LOCATION: 'text' },
    },
  ];

  for (const template of templates) {
    try {
      await templatesService.create(template);
      console.log(`✓ Created template: ${template.name}`);
    } catch (error) {
      console.error(`✗ Failed to create template: ${template.name}`);
    }
  }

  // Create some communication packs
  console.log('\n📦 Creating communication packs...');
  const packs = [
    { name: 'Q1 2025 Communications', description: 'All Q1 2025 related communications' },
    { name: 'Policy Updates 2025', description: 'Policy changes and updates for 2025' },
    { name: 'Leadership Messages', description: 'Messages from executive leadership' },
  ];

  for (const pack of packs) {
    try {
      await packsService.create(pack);
      console.log(`✓ Created pack: ${pack.name}`);
    } catch (error) {
      console.error(`✗ Failed to create pack: ${pack.name}`);
    }
  }

  console.log('\n🎉 Mock data seeding complete!\n');
}

// Run the seed script
seedMockData()
  .then(() => {
    console.log('✅ All done!');
    process.exit(0);
  })
  .catch((error) => {
    console.error('❌ Seeding failed:', error);
    process.exit(1);
  });