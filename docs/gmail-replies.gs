/**
 * Research brief: collect reader replies for deep dives.
 *
 * Runs inside the Gmail account that receives replies to the brief. Every hour it
 * looks for new replies to "Calvin Research Brief" emails and saves each one as
 * inbox/<message id>.json in the GitHub repository. The Monday run reads those
 * files, finds the paper IDs (A1, B2 ...) and writes the deep dives.
 *
 * Setup (once):
 *   1. Go to https://script.google.com while signed in to that Gmail account,
 *      click "New project" and paste this whole file in place of the sample code.
 *   2. Project Settings (gear icon) > Script Properties > Add script property:
 *        GITHUB_TOKEN = a fine-grained GitHub token with "Contents: Read and write"
 *                       on the research-brief-rss repository only.
 *   3. Back in the editor, choose the function "setup" and click Run.
 *      Google asks for permission to read Gmail and connect to an external
 *      service: click Allow. setup() schedules collectReplies() every hour.
 *
 * Only the start of each reply (above the quoted email, at most 1,000 characters),
 * its date, subject and a message id are saved. The sender's address is not.
 */

const REPO = 'calvinchengyx/research-brief-rss';
const BRANCH = 'main';
const SUBJECT = 'Calvin Research Brief';

function setup() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('collectReplies').timeBased().everyHours(1).create();
  collectReplies();
}

function collectReplies() {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Add GITHUB_TOKEN under Project Settings > Script Properties');
  const me = Session.getActiveUser().getEmail().toLowerCase();
  const done = JSON.parse(props.getProperty('DONE') || '[]');

  const threads = GmailApp.search('subject:"' + SUBJECT + '" newer_than:14d');
  threads.forEach(thread => {
    thread.getMessages().forEach(msg => {
      const id = msg.getId();
      if (done.indexOf(id) !== -1) return;
      if (!/^re:/i.test(msg.getSubject())) return;                 // only replies
      if (msg.getFrom().toLowerCase().indexOf(me) !== -1) return;  // not our own messages
      const reply = {
        id: id,
        date: msg.getDate().toISOString(),
        subject: msg.getSubject(),
        body: topOfReply(msg.getPlainBody()),
      };
      save(token, id, reply);
      done.push(id);
    });
  });
  props.setProperty('DONE', JSON.stringify(done.slice(-500)));
}

function topOfReply(body) {
  const kept = [];
  const lines = body.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*>/.test(line) || /^\s*On .+ wrote:\s*$/.test(line) || /-----Original Message/.test(line)) break;
    kept.push(line);
  }
  return kept.join('\n').slice(0, 1000);
}

function save(token, id, reply) {
  const url = 'https://api.github.com/repos/' + REPO + '/contents/inbox/' + id + '.json';
  const content = Utilities.base64Encode(JSON.stringify(reply, null, 1), Utilities.Charset.UTF_8);
  const resp = UrlFetchApp.fetch(url, {
    method: 'put',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
    payload: JSON.stringify({ message: 'Reader reply ' + id, content: content, branch: BRANCH }),
    muteHttpExceptions: true,
  });
  const code = resp.getResponseCode();
  if (code !== 201 && code !== 422) {  // 422: already saved
    throw new Error('GitHub refused reply ' + id + ' (' + code + '): ' + resp.getContentText().slice(0, 300));
  }
}
