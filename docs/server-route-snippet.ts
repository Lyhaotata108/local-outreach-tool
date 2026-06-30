// local-business-test/server.ts 里的 /api/leads 路由示例
// 关键点：邮件通知正文里增加 Outreach Lead ID，方便回到外联CSV查原始商家信息。

app.post('/api/leads', async (req, res) => {
  const { email, score, answers, topProblems, name, website, businessType, categoryScores, mainIssueCategory, lead_id } = req.body;

  const smtpEmail = process.env.SMTP_EMAIL;
  const smtpPassword = process.env.SMTP_PASSWORD;
  const notifyEmail = process.env.NOTIFICATION_EMAIL || smtpEmail;

  if (!smtpEmail || !smtpPassword) {
    console.error('Missing SMTP credentials in environment variables.');
    return res.status(500).json({ error: 'Email configuration is missing on the server.' });
  }

  try {
    const transporter = nodemailer.createTransport({
      service: 'gmail',
      auth: {
        user: smtpEmail,
        pass: smtpPassword,
      },
    });

    const formattedAnswers = Object.entries(answers || {}).map(([key, value]) => `${key}: ${value}`).join('\n');
    const formattedProblems = topProblems?.length
      ? topProblems.map((p: string, i: number) => `${i + 1}. ${p}`).join('\n')
      : 'None detected';

    const categoryLabels: Record<string, string> = {
      visibility: 'Visibility',
      trust: 'Trust',
      conversion: 'Conversion',
      offer: 'Offer/Positioning',
      retention: 'Retention',
      competition: 'Competition',
    };
    const categoryMax: Record<string, number> = {
      visibility: 22.5,
      trust: 22.5,
      conversion: 25,
      offer: 15,
      retention: 15,
      competition: 10,
    };
    const formattedCategoryScores = categoryScores
      ? Object.entries(categoryScores)
          .map(([cat, val]) => `  ${categoryLabels[cat] || cat}: ${val} / ${categoryMax[cat] ?? '?'}`)
          .join('\n')
      : '  N/A';

    const mainIssueLabel = mainIssueCategory ? (categoryLabels[mainIssueCategory] || mainIssueCategory) : 'N/A';

    // 紧急程度标记，方便邮箱里一眼判断要不要优先跟进
    const urgency = score < 40 ? '🔴 HIGH PRIORITY (High Risk)'
      : score < 60 ? '🟠 Major Customer Loss Risk'
      : score < 75 ? '🟡 Growth Leaks Detected'
      : '🟢 Healthy';

    const mailOptions = {
      from: smtpEmail,
      to: notifyEmail,
      subject: `[${urgency.split(' ')[0]}] New Lead: ${businessType || 'Local Business'} - Score ${score}/100`,
      text: `
New lead from the Local Business Diagnostic Tool!

Status: ${urgency}

Contact Details:
Outreach Lead ID: ${lead_id || 'N/A (direct visit)'}
Email: ${email}
Name: ${name || 'N/A'}
Website: ${website || 'N/A'}

Diagnostic Results:
Overall Score: ${score}/100
Main Issue Area: ${mainIssueLabel}

Category Breakdown:
${formattedCategoryScores}

Top Problems Found:
${formattedProblems}

Full Answers:
${formattedAnswers}
      `,
    };

    await transporter.sendMail(mailOptions);
    res.json({ success: true });
  } catch (error) {
    console.error('Error sending email:', error);
    res.status(500).json({ error: 'Failed to send email' });
  }
});
