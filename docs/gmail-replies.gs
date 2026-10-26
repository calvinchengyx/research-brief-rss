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
 * its date, subject and a message id are saved. The sender's address is not: it is
 * replaced by an anonymous code (a keyed hash, so each reader votes once per paper)
 * and an "owner" flag for replies from the addresses in OWNER, whose picks win ties.
 *
 * Updating from an earlier version: paste the whole file again and click Save.
 * The hourly schedule keeps running; there is no need to run setup() again.
 */

const REPO = 'calvinchengyx/research-brief-rss';
const BRANCH = 'main';
const SUBJECT = 'Calvin Research Brief';
const OWNER = ['owencheng1992930@gmail.com', 'yixiang.cheng@uzh.ch'];  // Calvin's addresses

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
  let salt = props.getProperty('SALT');
  if (!salt) { salt = Utilities.getUuid(); props.setProperty('SALT', salt); }
  const done = JSON.parse(props.getProperty('DONE') || '[]');

  const threads = GmailApp.search('subject:"' + SUBJECT + '" newer_than:14d');
  threads.forEach(thread => {
    thread.getMessages().forEach(msg => {
      const id = msg.getId();
      if (done.indexOf(id) !== -1) return;
      if (!/^re:/i.test(msg.getSubject())) return;                 // only replies
      const from = msg.getFrom().toLowerCase();
      if (from.indexOf(me) !== -1) return;                        // not our own messages
      const address = (from.match(/[^\s<>"]+@[^\s<>"]+/) || [from])[0];
      const reply = {
        id: id,
        sender: anonymous(salt, address),
        owner: OWNER.indexOf(address) !== -1,
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

function anonymous(salt, address) {
  const mac = Utilities.computeHmacSha256Signature(address, salt);
  return mac.slice(0, 8).map(b => ((b + 256) % 256).toString(16).padStart(2, '0')).join('');
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
