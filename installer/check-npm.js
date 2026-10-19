// Load the modules used by npm ci/install. --version alone misses broken npm
// dependencies left behind when one distribution was copied over another.
'use strict';
const path = require('node:path');
const root = path.resolve(process.argv[2]);
const metadata = require(path.join(root, 'package.json'));
if (metadata.name !== 'npm') throw Error('This directory is not an npm distribution');
require(path.join(root, 'lib', 'commands', 'ci.js'));
require(path.join(root, 'lib', 'commands', 'install.js'));
require(require.resolve('@npmcli/arborist', { paths: [root] }));
console.log(`npm ${metadata.version}: installation modules loaded`);
